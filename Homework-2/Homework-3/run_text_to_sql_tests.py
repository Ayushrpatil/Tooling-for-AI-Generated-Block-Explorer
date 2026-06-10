from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from openai import APIStatusError, OpenAI, RateLimitError


DEFAULT_MODEL = "gpt-5.4-mini"
SYSTEM_PROMPT = (
    "You are a SQL developer that is expert in Bitcoin and you answer "
    "natural language questions about the bitcoind database in a sqlite "
    "database. You always only respond with SQL statements that are correct. "
    "If the question cannot be solved from the available schema, return exactly: CANNOT_ANSWER"
)
FORBIDDEN_SQL_PATTERN = re.compile(
    r"\b(insert|update|delete|replace|alter|drop|create|attach|detach|pragma|vacuum|reindex|analyze)\b",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Homework 3 text-to-SQL test cases against the SQLite Bitcoin database."
    )
    parser.add_argument("--sqlite-db", required=True, help="Absolute path to the SQLite database.")
    parser.add_argument(
        "--cases",
        default=str(Path(__file__).with_name("test_cases.json")),
        help="Path to standard test cases JSON.",
    )
    parser.add_argument(
        "--hard-cases",
        default=str(Path(__file__).with_name("hard_test_cases.json")),
        help="Path to hard test cases JSON.",
    )
    parser.add_argument(
        "--rejection-cases",
        default=str(Path(__file__).with_name("rejection_test_cases.json")),
        help="Path to rejection test cases JSON.",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).with_name("test_report.md")),
        help="Markdown report output path.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    return parser.parse_args()


def ensure_db(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        raise ValueError("--sqlite-db must be an absolute path.")
    if not path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {path}")
    return path


def extract_schema(db_path: Path) -> str:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    finally:
        connection.close()
    return "\n\n".join(row[0] for row in rows if row[0])


def build_messages(schema: str, question: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": f"SQLite schema:\n{schema}\n\nQuestion:\n{question}\n",
        },
    ]


def extract_sql(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return text


def execute_sql(db_path: Path, sql: str) -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(sql).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def is_read_only_sql(sql: str) -> bool:
    stripped = sql.strip().rstrip(";").strip().lower()
    if not (stripped.startswith("select") or stripped.startswith("with")):
        return False
    if FORBIDDEN_SQL_PATTERN.search(stripped):
        return False
    if stripped.startswith("with") and "select" not in stripped:
        return False
    return True


def load_cases(path_str: str) -> list[dict[str, Any]]:
    return json.loads(Path(path_str).read_text(encoding="utf-8"))


def values_match(expected: Any, actual: Any) -> bool:
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(float(expected), float(actual), rel_tol=1e-9, abs_tol=1e-6)
    return expected == actual


def rows_match(expected_rows: list[dict[str, Any]], actual_rows: list[dict[str, Any]]) -> bool:
    if len(expected_rows) != len(actual_rows):
        return False

    for expected_row, actual_row in zip(expected_rows, actual_rows):
        if expected_row.keys() == actual_row.keys():
            if not all(values_match(expected_row[key], actual_row[key]) for key in expected_row):
                return False
            continue

        expected_values = list(expected_row.values())
        actual_values = list(actual_row.values())
        if len(expected_values) != len(actual_values):
            return False
        if not all(values_match(expected, actual) for expected, actual in zip(expected_values, actual_values)):
            return False

    return True


def run_cases(
    client: OpenAI,
    model: str,
    schema: str,
    db_path: Path,
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases:
        expected_answer = execute_sql(db_path, case["expected_sql"])
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=build_messages(schema, case["question"]),
                temperature=0,
            )
        except RateLimitError as exc:
            raise RuntimeError(
                "OpenAI request failed: insufficient quota or rate limit. "
                "Check billing, credits, and model access for this API key."
            ) from exc
        except APIStatusError as exc:
            raise RuntimeError(f"OpenAI API returned HTTP {exc.status_code}: {exc}") from exc
        raw = completion.choices[0].message.content or ""
        generated_sql = extract_sql(raw)

        if generated_sql == "CANNOT_ANSWER":
            generated_answer: list[dict[str, Any]] | str = "CANNOT_ANSWER"
            passed = False
        elif not is_read_only_sql(generated_sql):
            generated_answer = f"INVALID_SQL: expected a read-only query, got: {generated_sql}"
            passed = False
        else:
            try:
                generated_answer = execute_sql(db_path, generated_sql)
                passed = rows_match(expected_answer, generated_answer)
            except sqlite3.DatabaseError as exc:
                generated_answer = f"SQL_EXECUTION_ERROR: {exc}"
                passed = False

        results.append(
            {
                "id": case["id"],
                "question": case["question"],
                "expected_sql": case["expected_sql"],
                "expected_answer": expected_answer,
                "generated_sql": generated_sql,
                "generated_answer": generated_answer,
                "passed": passed,
            }
        )
    return results


def run_rejection_cases(
    client: OpenAI,
    model: str,
    schema: str,
    db_path: Path,
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases:
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=build_messages(schema, case["question"]),
                temperature=0,
            )
        except RateLimitError as exc:
            raise RuntimeError(
                "OpenAI request failed: insufficient quota or rate limit. "
                "Check billing, credits, and model access for this API key."
            ) from exc
        except APIStatusError as exc:
            raise RuntimeError(f"OpenAI API returned HTTP {exc.status_code}: {exc}") from exc
        raw = completion.choices[0].message.content or ""
        generated_sql = extract_sql(raw)

        if generated_sql == "CANNOT_ANSWER":
            generated_answer: list[dict[str, Any]] | str = "CANNOT_ANSWER"
            passed = True
        elif not is_read_only_sql(generated_sql):
            generated_answer = f"INVALID_SQL: expected CANNOT_ANSWER, got: {generated_sql}"
            passed = False
        else:
            try:
                generated_answer = execute_sql(db_path, generated_sql)
            except sqlite3.DatabaseError as exc:
                generated_answer = f"SQL_EXECUTION_ERROR: {exc}"
            passed = False

        results.append(
            {
                "id": case["id"],
                "question": case["question"],
                "expected_behavior": "CANNOT_ANSWER",
                "generated_sql": generated_sql,
                "generated_answer": generated_answer,
                "passed": passed,
            }
        )
    return results


def count_passed(results: list[dict[str, Any]]) -> tuple[int, int]:
    passed = sum(1 for result in results if result["passed"])
    return passed, len(results)


def render_report(
    standard_results: list[dict[str, Any]],
    rejection_results: list[dict[str, Any]],
    hard_results: list[dict[str, Any]],
) -> str:
    lines: list[str] = ["# Homework 3 Test Report", ""]
    standard_passed, standard_total = count_passed(standard_results)
    rejection_passed, rejection_total = count_passed(rejection_results)
    hard_passed, hard_total = count_passed(hard_results)

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Standard cases passed: {standard_passed}/{standard_total}")
    lines.append(f"- Rejection cases passed: {rejection_passed}/{rejection_total}")
    lines.append(f"- Hard cases passed: {hard_passed}/{hard_total}")
    lines.append("")

    lines.append("## Standard Cases")
    lines.append("")
    for result in standard_results:
        lines.append(f"### {result['id']}")
        lines.append("")
        lines.append(f"- Question: {result['question']}")
        lines.append(f"- Passed: {result['passed']}")
        lines.append("- Expected SQL:")
        lines.append("```sql")
        lines.append(result["expected_sql"])
        lines.append("```")
        lines.append("- Expected answer:")
        lines.append("```json")
        lines.append(json.dumps(result["expected_answer"], indent=2))
        lines.append("```")
        lines.append("- Generated SQL:")
        lines.append("```sql")
        lines.append(result["generated_sql"])
        lines.append("```")
        lines.append("- Generated answer:")
        lines.append("```json")
        lines.append(json.dumps(result["generated_answer"], indent=2))
        lines.append("```")
        lines.append("")

    lines.append("## Rejection Cases")
    lines.append("")
    for result in rejection_results:
        lines.append(f"### {result['id']}")
        lines.append("")
        lines.append(f"- Question: {result['question']}")
        lines.append(f"- Expected behavior: {result['expected_behavior']}")
        lines.append(f"- Passed: {result['passed']}")
        lines.append("- Generated SQL:")
        lines.append("```sql")
        lines.append(result["generated_sql"])
        lines.append("```")
        lines.append("- Generated answer:")
        lines.append("```json")
        lines.append(json.dumps(result["generated_answer"], indent=2))
        lines.append("```")
        lines.append("")

    lines.append("## Hard Cases")
    lines.append("")
    for result in hard_results:
        lines.append(f"### {result['id']}")
        lines.append("")
        lines.append(f"- Question: {result['question']}")
        lines.append(f"- Passed: {result['passed']}")
        lines.append("- Expected SQL:")
        lines.append("```sql")
        lines.append(result["expected_sql"])
        lines.append("```")
        lines.append("- Expected answer:")
        lines.append("```json")
        lines.append(json.dumps(result["expected_answer"], indent=2))
        lines.append("```")
        lines.append("- Incorrect / generated SQL:")
        lines.append("```sql")
        lines.append(result["generated_sql"])
        lines.append("```")
        lines.append("- Incorrect / generated answer:")
        lines.append("```json")
        lines.append(json.dumps(result["generated_answer"], indent=2))
        lines.append("```")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    try:
        db_path = ensure_db(args.sqlite_db)
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    schema = extract_schema(db_path)
    standard_cases = load_cases(args.cases)
    rejection_cases = load_cases(args.rejection_cases)
    hard_cases = load_cases(args.hard_cases)
    client = OpenAI()

    try:
        standard_results = run_cases(client, args.model, schema, db_path, standard_cases)
        rejection_results = run_rejection_cases(
            client,
            args.model,
            schema,
            db_path,
            rejection_cases,
        )
        hard_results = run_cases(client, args.model, schema, db_path, hard_cases)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    report = render_report(standard_results, rejection_results, hard_results)
    Path(args.output).write_text(report, encoding="utf-8")
    print(f"Wrote report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
