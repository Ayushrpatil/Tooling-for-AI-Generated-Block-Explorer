from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from bitcoin_rpc import BitcoinRPC, BitcoinRPCError, RPCConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show Bitcoin node sync status and optional SQLite sync status."
    )
    parser.add_argument(
        "--rpc-url",
        default=os.getenv("BTC_RPC_URL", "http://127.0.0.1:8332"),
        help="Bitcoin JSON-RPC URL. Default: http://127.0.0.1:8332",
    )
    parser.add_argument("--rpc-user", default=os.getenv("BTC_RPC_USER"))
    parser.add_argument("--rpc-password", default=os.getenv("BTC_RPC_PASSWORD"))
    parser.add_argument(
        "--rpc-cookie-file",
        default=os.getenv("BTC_RPC_COOKIE_FILE"),
        help="Path to the Bitcoin RPC cookie file, if using cookie authentication.",
    )
    parser.add_argument(
        "--sqlite-db",
        help="Optional absolute path to the SQLite database for comparing node and DB progress.",
    )
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def load_db_status(db_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(db_path)
    try:
        blocks_row = connection.execute(
            """
            SELECT COUNT(*) AS block_count, MAX(height) AS latest_height
            FROM blocks
            """
        ).fetchone()
        latest_row = connection.execute(
            """
            SELECT block_hash, height, tx_count, block_time
            FROM blocks
            ORDER BY height DESC
            LIMIT 1
            """
        ).fetchone()
        tx_row = connection.execute("SELECT COUNT(*) AS transaction_count FROM transactions").fetchone()
    finally:
        connection.close()

    latest_height = blocks_row[1] if blocks_row else None
    latest_hash = latest_row[0] if latest_row else None

    return {
        "block_count": int(blocks_row[0]) if blocks_row and blocks_row[0] is not None else 0,
        "latest_height": int(latest_height) if latest_height is not None else None,
        "latest_block_hash": latest_hash,
        "latest_block_tx_count": int(latest_row[2]) if latest_row and latest_row[2] is not None else None,
        "latest_block_time": int(latest_row[3]) if latest_row and latest_row[3] is not None else None,
        "transaction_count": int(tx_row[0]) if tx_row and tx_row[0] is not None else 0,
    }


def main() -> int:
    args = parse_args()

    db_path: Path | None = None
    if args.sqlite_db:
        db_path = Path(args.sqlite_db)
        if not db_path.is_absolute():
            print("--sqlite-db must be an absolute path.", file=sys.stderr)
            return 1
        if not db_path.is_file():
            print(f"SQLite database not found: {db_path}", file=sys.stderr)
            return 1

    rpc = BitcoinRPC(
        RPCConfig(
            url=args.rpc_url,
            rpc_user=args.rpc_user,
            rpc_password=args.rpc_password,
            rpc_cookie_file=args.rpc_cookie_file,
        )
    )

    try:
        blockchain_info = rpc.call("getblockchaininfo")
        best_block_hash = str(blockchain_info["bestblockhash"])
        best_block = rpc.call("getblock", [best_block_hash, 2])
        block_count = int(rpc.call("getblockcount"))
    except BitcoinRPCError as exc:
        print(f"Status check failed: {exc}", file=sys.stderr)
        return 1

    canonical_height = int(best_block["height"])
    getblockchaininfo_blocks = int(blockchain_info["blocks"])
    sync_note = None
    if block_count != canonical_height or getblockchaininfo_blocks != canonical_height:
        sync_note = (
            "During active sync, getblockchaininfo, getblockcount, and getblock(bestblockhash) "
            "can be observed at slightly different moments."
        )

    result: dict[str, Any] = {
        "node": {
            "chain": blockchain_info.get("chain"),
            "blocks_from_getblockchaininfo": getblockchaininfo_blocks,
            "headers": int(blockchain_info["headers"]),
            "verificationprogress": blockchain_info.get("verificationprogress"),
            "initialblockdownload": blockchain_info.get("initialblockdownload"),
            "bestblockhash_from_getblockchaininfo": best_block_hash,
            "getblockcount_observed": block_count,
            "last_downloaded_block_via_getblock": {
                "hash": best_block["hash"],
                "height": canonical_height,
                "time": int(best_block["time"]),
                "tx_count": int(best_block["nTx"]),
            },
        }
    }
    if sync_note:
        result["node"]["sync_observation_note"] = sync_note

    if db_path:
        database_status = load_db_status(db_path)
        latest_height = database_status["latest_height"]
        result["database"] = database_status
        result["lag_vs_node_blocks"] = (
            canonical_height - latest_height if latest_height is not None else None
        )

    print(json.dumps(result, indent=2, default=json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
