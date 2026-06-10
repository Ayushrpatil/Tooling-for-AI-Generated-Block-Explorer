from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

from openai import APIStatusError, OpenAI, RateLimitError


DEFAULT_MODEL = "gpt-5.4-mini"
SYSTEM_PROMPT = (
    "You are a SQL developer that is expert in Bitcoin and you answer natural "
    "language questions about the bitcoind database in a sqlite database. "
    "You always only respond with SQL statements that are correct. "
    "If the question cannot be solved from the available schema, return exactly: CANNOT_ANSWER"
)
FORBIDDEN_SQL_PATTERN = re.compile(
    r"\b(insert|update|delete|replace|alter|drop|create|attach|detach|pragma|vacuum|reindex|analyze)\b",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Answer natural language Bitcoin questions by generating and executing SQLite SQL."
    )
    parser.add_argument("--question", required=True, help="Natural language Bitcoin question.")
    parser.add_argument(
        "--sqlite-db",
        required=True,
        help="Absolute path to the SQLite database file.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenAI Chat Completions model to use. Default: {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--sql-only",
        action="store_true",
        help="Only print the generated SQL or CANNOT_ANSWER.",
    )
    return parser.parse_args()


def ensure_absolute_db_path(path_str: str) -> Path:
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
            SELECT name, sql
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    finally:
        connection.close()

    statements = [row[1] for row in rows if row[1]]
    return "\n\n".join(statements)


def build_messages(schema: str, question: str) -> list[dict[str, str]]:
    user_prompt = f"""SQLite schema:
{schema}

Question:
{question}
"""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def extract_sql(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return text


def validate_sql(sql: str) -> None:
    stripped = sql.strip().rstrip(";").strip()
    lowered = stripped.lower()
    if lowered == "cannot_answer":
        return
    if ";" in stripped:
        raise ValueError("Only a single SQL statement is allowed.")
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ValueError("Generated SQL must be a read-only SELECT or WITH query.")
    if FORBIDDEN_SQL_PATTERN.search(stripped):
        raise ValueError("Generated SQL contains a forbidden write or admin keyword.")
    if lowered.startswith("with") and "select" not in lowered:
        raise ValueError("WITH statements must resolve to a SELECT query.")


def execute_sql(db_path: Path, sql: str) -> list[dict[str, object]]:
    connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(sql).fetchall()
    finally:
        connection.close()

    return [dict(row) for row in rows]


def main() -> int:
    args = parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    try:
        db_path = ensure_absolute_db_path(args.sqlite_db)
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    schema = extract_schema(db_path)
    client = OpenAI()

    try:
        completion = client.chat.completions.create(
            model=args.model,
            messages=build_messages(schema, args.question),
            temperature=0,
        )
    except RateLimitError as exc:
        print(
            "OpenAI request failed: insufficient quota or rate limit. "
            "Check billing, credits, and model access for this API key.",
            file=sys.stderr,
        )
        print(str(exc), file=sys.stderr)
        return 1
    except APIStatusError as exc:
        print(f"OpenAI API returned HTTP {exc.status_code}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"OpenAI API request failed: {exc}", file=sys.stderr)
        return 1

    content = completion.choices[0].message.content or ""
    sql = extract_sql(content)

    try:
        validate_sql(sql)
    except ValueError as exc:
        print(f"Generated SQL failed validation: {exc}", file=sys.stderr)
        print(sql)
        return 1

    if args.sql_only or sql == "CANNOT_ANSWER":
        print(sql)
        return 0

    rows = execute_sql(db_path, sql)
    print("SQL:")
    print(sql)
    print("")
    print("Answer:")
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
