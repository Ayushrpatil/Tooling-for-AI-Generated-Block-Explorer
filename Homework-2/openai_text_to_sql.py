import argparse
import os
import sys
from pathlib import Path

from openai import OpenAI


DEFAULT_MODEL = "gpt-5.4-mini"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate SQL from a SQL schema and a natural language question."
    )
    parser.add_argument(
        "--schema-file",
        required=True,
        help="Path to a file containing CREATE TABLE statements.",
    )
    parser.add_argument(
        "--question",
        required=True,
        help="Natural language question to translate into SQL.",
    )
    parser.add_argument(
        "--dialect",
        default="PostgreSQL",
        help="Target SQL dialect. Default: PostgreSQL.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Chat Completions model to use. Default: {DEFAULT_MODEL}.",
    )
    return parser.parse_args()


def load_schema(path_str: str) -> str:
    path = Path(path_str)
    if not path.is_file():
        raise FileNotFoundError(f"Schema file not found: {path}")
    return path.read_text(encoding="utf-8")


def extract_sql(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return text


def build_messages(schema: str, question: str, dialect: str) -> list[dict[str, str]]:
    developer_prompt = (
        "You are a text-to-SQL assistant. "
        "Convert the user's question into a single SQL query using only the provided schema. "
        "Return SQL only. Do not include Markdown, comments, or explanations. "
        "If the question cannot be answered from the schema, return exactly: CANNOT_ANSWER"
    )

    user_prompt = f"""SQL dialect: {dialect}

Schema:
{schema}

Question:
{question}
"""

    return [
        {"role": "developer", "content": developer_prompt},
        {"role": "user", "content": user_prompt},
    ]


def main() -> int:
    args = parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    try:
        schema = load_schema(args.schema_file)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    client = OpenAI()

    try:
        completion = client.chat.completions.create(
            model=args.model,
            messages=build_messages(schema, args.question, args.dialect),
            temperature=0,
        )
    except Exception as exc:
        print(f"OpenAI API request failed: {exc}", file=sys.stderr)
        return 1

    content = completion.choices[0].message.content or ""
    sql = extract_sql(content)

    print(sql)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
