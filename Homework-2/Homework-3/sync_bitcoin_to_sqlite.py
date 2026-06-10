from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from bitcoin_rpc import BitcoinRPC, BitcoinRPCError, RPCConfig


SATOSHIS = Decimal("100000000")
SCHEMA_PATH = Path(__file__).with_name("bitcoin_schema.sql")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync Bitcoin blocks and transactions from Bitcoin RPC into SQLite."
    )
    parser.add_argument(
        "--sqlite-db",
        required=True,
        help="Absolute path to the SQLite database file to create/update.",
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
        "--start-height",
        type=int,
        help="Optional starting block height. Default is derived from the database state.",
    )
    parser.add_argument(
        "--stop-height",
        type=int,
        help="Optional inclusive ending block height. Default is the current node tip.",
    )
    parser.add_argument(
        "--max-blocks",
        type=int,
        help="Optional maximum number of new blocks to process in this run.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=int,
        default=0,
        help="If > 0, continue polling and syncing every N seconds.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of blocks to fetch and commit per batch. Default: 50.",
    )
    parser.add_argument(
        "--sqlite-synchronous",
        choices=("FULL", "NORMAL", "OFF"),
        default="FULL",
        help="SQLite synchronous mode. Use NORMAL to speed catch-up. Default: FULL.",
    )
    return parser.parse_args()


def to_json_text(value: Any) -> str:
    def default(obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return str(obj)
        raise TypeError(f"Object of type {type(obj)!r} is not JSON serializable")

    return json.dumps(value, default=default, sort_keys=True)


def sats_from_btc(value: Decimal | int | str) -> int:
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return int((amount * SATOSHIS).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def connect_sqlite(db_path: Path, synchronous: str) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(f"PRAGMA synchronous = {synchronous}")
    connection.execute("PRAGMA temp_store = MEMORY")
    connection.execute("PRAGMA cache_size = -65536")
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def metadata_get(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute(
        "SELECT value FROM sync_metadata WHERE key = ?",
        (key,),
    ).fetchone()
    return row[0] if row else None


def metadata_set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        """
        INSERT INTO sync_metadata(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def local_tip(connection: sqlite3.Connection) -> tuple[int | None, str | None]:
    row = connection.execute(
        "SELECT height, block_hash FROM blocks ORDER BY height DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None, None
    return int(row[0]), str(row[1])


def rollback_reorg(connection: sqlite3.Connection, rpc: BitcoinRPC) -> int:
    tip_height, tip_hash = local_tip(connection)
    if tip_height is None or tip_hash is None:
        return 0

    height = tip_height
    while height >= 0:
        local_hash = connection.execute(
            "SELECT block_hash FROM blocks WHERE height = ?",
            (height,),
        ).fetchone()[0]
        remote_hash = rpc.call("getblockhash", [height])
        if local_hash == remote_hash:
            break
        height -= 1

    if height == tip_height:
        return 0

    delete_from = 0 if height < 0 else height + 1
    connection.execute("DELETE FROM blocks WHERE height >= ?", (delete_from,))
    metadata_set(connection, "last_reorg_rollback_height", str(delete_from))
    return delete_from


def upsert_block(connection: sqlite3.Connection, block: dict[str, Any]) -> None:
    connection.execute("DELETE FROM blocks WHERE block_hash = ?", (block["hash"],))
    connection.execute(
        """
        INSERT INTO blocks (
            block_hash, height, confirmations, size, stripped_size, weight, version,
            version_hex, merkle_root, block_time, median_time, nonce, bits,
            difficulty, chainwork, tx_count, previous_block_hash, next_block_hash,
            raw_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            block["hash"],
            block["height"],
            block.get("confirmations"),
            block["size"],
            block.get("strippedsize"),
            block.get("weight"),
            block["version"],
            block["versionHex"],
            block["merkleroot"],
            block["time"],
            block.get("mediantime"),
            block["nonce"],
            block["bits"],
            float(block["difficulty"]),
            block["chainwork"],
            block["nTx"],
            block.get("previousblockhash"),
            block.get("nextblockhash"),
            to_json_text(block),
        ),
    )


def upsert_transaction(
    connection: sqlite3.Connection,
    block: dict[str, Any],
    tx: dict[str, Any],
    tx_index: int,
) -> None:
    connection.execute("DELETE FROM transactions WHERE txid = ?", (tx["txid"],))

    is_coinbase = int(bool(tx.get("vin")) and "coinbase" in tx["vin"][0])
    connection.execute(
        """
        INSERT INTO transactions (
            txid, block_hash, block_height, tx_index, in_active_chain, hex, tx_hash,
            size, vsize, weight, version, locktime, confirmations, block_time, time,
            is_coinbase, raw_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            tx["txid"],
            block["hash"],
            block["height"],
            tx_index,
            int(tx["in_active_chain"]) if "in_active_chain" in tx else None,
            tx.get("hex"),
            tx["hash"],
            tx["size"],
            tx["vsize"],
            tx["weight"],
            tx["version"],
            tx["locktime"],
            tx.get("confirmations", block.get("confirmations")),
            tx.get("blocktime", block["time"]),
            tx.get("time", block["time"]),
            is_coinbase,
            to_json_text(tx),
        ),
    )

    for vin_index, vin in enumerate(tx["vin"]):
        script_sig = vin.get("scriptSig", {})
        connection.execute(
            """
            INSERT INTO transaction_inputs (
                txid, vin_index, coinbase, prev_txid, prev_vout, script_sig_asm,
                script_sig_hex, sequence, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tx["txid"],
                vin_index,
                vin.get("coinbase"),
                vin.get("txid"),
                vin.get("vout"),
                script_sig.get("asm"),
                script_sig.get("hex"),
                vin["sequence"],
                to_json_text(vin),
            ),
        )

        for witness_index, witness_hex in enumerate(vin.get("txinwitness", [])):
            connection.execute(
                """
                INSERT INTO transaction_input_witness (
                    txid, vin_index, witness_index, witness_hex
                ) VALUES (?, ?, ?, ?)
                """,
                (tx["txid"], vin_index, witness_index, witness_hex),
            )

    for vout in tx["vout"]:
        script_pub_key = vout.get("scriptPubKey", {})
        value = Decimal(str(vout["value"]))
        connection.execute(
            """
            INSERT INTO transaction_outputs (
                txid, vout_index, value_btc_text, value_sats, script_pubkey_asm,
                script_pubkey_hex, script_pubkey_req_sigs, script_pubkey_type, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tx["txid"],
                vout["n"],
                str(value),
                sats_from_btc(value),
                script_pub_key.get("asm"),
                script_pub_key.get("hex"),
                script_pub_key.get("reqSigs"),
                script_pub_key.get("type"),
                to_json_text(vout),
            ),
        )

        for address_index, address in enumerate(script_pub_key.get("addresses", [])):
            connection.execute(
                """
                INSERT INTO transaction_output_addresses (
                    txid, vout_index, address_index, address
                ) VALUES (?, ?, ?, ?)
                """,
                (tx["txid"], vout["n"], address_index, address),
            )


def sync_once(
    connection: sqlite3.Connection,
    rpc: BitcoinRPC,
    start_height: int | None,
    stop_height: int | None,
    max_blocks: int | None,
    batch_size: int,
) -> tuple[int, int]:
    ensure_schema(connection)
    rollback_reorg(connection, rpc)

    tip_height = int(rpc.call("getblockcount"))
    local_height, _ = local_tip(connection)
    next_height = start_height if start_height is not None else (0 if local_height is None else local_height + 1)
    final_height = tip_height if stop_height is None else min(stop_height, tip_height)

    processed = 0
    height = next_height
    while height <= final_height:
        if max_blocks is not None and processed >= max_blocks:
            break

        remaining = final_height - height + 1
        if max_blocks is not None:
            remaining = min(remaining, max_blocks - processed)

        current_batch_size = min(batch_size, remaining)
        heights = list(range(height, height + current_batch_size))

        if len(heights) == 1:
            block_hashes = [rpc.call("getblockhash", [heights[0]])]
        else:
            block_hashes = rpc.batch_call([("getblockhash", [batch_height]) for batch_height in heights])

        if len(block_hashes) == 1:
            blocks = [rpc.call("getblock", [block_hashes[0], 2])]
        else:
            blocks = rpc.batch_call([("getblock", [block_hash, 2]) for block_hash in block_hashes])

        with connection:
            for block_hash, block in zip(block_hashes, blocks):
                upsert_block(connection, block)
                for tx_index, tx in enumerate(block["tx"]):
                    upsert_transaction(connection, block, tx, tx_index)

                processed += 1
                last_height = int(block["height"])
                metadata_set(connection, "last_synced_height", str(last_height))
                metadata_set(connection, "last_synced_block_hash", block_hash)
                metadata_set(connection, "last_sync_timestamp", str(int(time.time())))

        last_height = heights[-1]
        if processed <= current_batch_size or processed % 100 == 0:
            print(f"Synced through block {last_height} / {final_height}")

        height += current_batch_size

    return processed, final_height


def main() -> int:
    args = parse_args()

    db_path = Path(args.sqlite_db)
    if not db_path.is_absolute():
        print("--sqlite-db must be an absolute path.", file=sys.stderr)
        return 1

    db_path.parent.mkdir(parents=True, exist_ok=True)

    rpc = BitcoinRPC(
        RPCConfig(
            url=args.rpc_url,
            rpc_user=args.rpc_user,
            rpc_password=args.rpc_password,
            rpc_cookie_file=args.rpc_cookie_file,
        )
    )

    if args.batch_size <= 0:
        print("--batch-size must be a positive integer.", file=sys.stderr)
        return 1

    connection = connect_sqlite(db_path, args.sqlite_synchronous)

    try:
        while True:
            try:
                processed, tip_height = sync_once(
                    connection,
                    rpc,
                    args.start_height,
                    args.stop_height,
                    args.max_blocks,
                    args.batch_size,
                )
            except BitcoinRPCError as exc:
                print(f"Sync failed: {exc}", file=sys.stderr)
                return 1

            print(f"Run complete. Processed {processed} blocks. RPC tip was {tip_height}.")

            if args.poll_interval_seconds <= 0:
                break

            time.sleep(args.poll_interval_seconds)
            args.start_height = None
            args.max_blocks = None

    finally:
        connection.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
