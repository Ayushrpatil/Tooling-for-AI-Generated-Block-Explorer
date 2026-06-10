from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an approximate normalized SQLite schema from a sample JSON object."
    )
    parser.add_argument("--json-file", required=True, help="Path to a sample JSON file.")
    parser.add_argument(
        "--root-table",
        default="root_object",
        help="Name to use for the root table. Default: root_object.",
    )
    parser.add_argument(
        "--output",
        help="Optional output file path. If omitted, prints to stdout.",
    )
    return parser.parse_args()


def sqlite_type_for_value(value: Any) -> str:
    if isinstance(value, bool):
        return "INTEGER"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    if value is None:
        return "TEXT"
    return "TEXT"


def add_scalar_column(columns: dict[str, str], column_name: str, value: Any) -> None:
    if column_name not in columns:
        columns[column_name] = sqlite_type_for_value(value)


def walk_object(
    table_name: str,
    obj: dict[str, Any],
    tables: dict[str, dict[str, str]],
    child_tables: list[str],
    parent_table: str | None = None,
) -> None:
    if table_name not in tables:
        tables[table_name] = {"id": "INTEGER PRIMARY KEY"}
        if parent_table:
            parent_fk = f"{parent_table}_id"
            tables[table_name][parent_fk] = "INTEGER NOT NULL"
            tables[table_name]["item_index"] = "INTEGER"

    for key, value in obj.items():
        if isinstance(value, dict):
            if all(not isinstance(v, (dict, list)) for v in value.values()):
                for subkey, subvalue in value.items():
                    add_scalar_column(tables[table_name], f"{key}_{subkey}", subvalue)
            else:
                nested_table = f"{table_name}_{key}"
                walk_object(nested_table, value, tables, child_tables, parent_table=table_name)
                child_tables.append(nested_table)
        elif isinstance(value, list):
            nested_table = f"{table_name}_{key}"
            sample = next((item for item in value if item is not None), None)
            if isinstance(sample, dict):
                walk_object(nested_table, sample, tables, child_tables, parent_table=table_name)
            else:
                if nested_table not in tables:
                    tables[nested_table] = {
                        "id": "INTEGER PRIMARY KEY",
                        f"{table_name}_id": "INTEGER NOT NULL",
                        "item_index": "INTEGER NOT NULL",
                        "value": sqlite_type_for_value(sample),
                    }
            child_tables.append(nested_table)
        else:
            add_scalar_column(tables[table_name], key, value)


def render_sql(tables: dict[str, dict[str, str]]) -> str:
    chunks: list[str] = []
    for table_name, columns in tables.items():
        column_lines = [f"    {name} {column_type}" for name, column_type in columns.items()]
        statement = "CREATE TABLE IF NOT EXISTS {name} (\n{cols}\n);".format(
            name=table_name,
            cols=",\n".join(column_lines),
        )
        chunks.append(statement)
    return "\n\n".join(chunks) + "\n"


def main() -> int:
    args = parse_args()
    payload = json.loads(Path(args.json_file).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise SystemExit("Root JSON value must be an object.")

    tables: dict[str, dict[str, str]] = {}
    child_tables: list[str] = []
    walk_object(args.root_table, payload, tables, child_tables)
    sql = render_sql(tables)

    if args.output:
        Path(args.output).write_text(sql, encoding="utf-8")
    else:
        print(sql)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
