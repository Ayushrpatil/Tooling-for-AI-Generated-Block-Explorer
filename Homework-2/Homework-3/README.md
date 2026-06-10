# Homework 3 Support

This folder extends the Homework 2 repo into a Homework 3 solution for:

- syncing Bitcoin block and transaction data into SQLite
- designing a queryable SQL schema for `getblock` verbosity `2`
- generating SQL from natural language over that SQLite database
- running a repeatable text-to-SQL test suite

## Files

- `bitcoin_rpc.py`: reusable Bitcoin JSON-RPC client
- `bitcoin_schema.sql`: normalized SQLite schema for blocks, transactions, inputs, outputs, witness items, and output addresses
- `sync_bitcoin_to_sqlite.py`: incremental RPC-to-SQLite sync program
- `bitcoin_sync_status.py`: shows node sync status and optionally compares it to the SQLite database
- `bitcoin_text_to_sql.py`: natural-language question to SQL and answer runner
- `auto_schema_from_json.py`: bonus utility to auto-generate a first-pass SQL schema from sample JSON
- `test_cases.json`: 13 standard test cases from simple counts through joins and derived UTXO queries
- `rejection_test_cases.json`: questions the model should reject with `CANNOT_ANSWER`
- `hard_test_cases.json`: 3 intentionally difficult failure-oriented test cases
- `run_text_to_sql_tests.py`: executes expected SQL, generated SQL, and writes a markdown report
- `slide_hard_cases.md`: ready-to-present hard-case slide content
- `verify_homework3.ps1`: quick Windows verification script for Docker, RPC, SQLite, and OpenAI readiness

## 1. SQLite Schema Design

The schema is normalized around the actual nested shape of `getblock(hash, 2)`:

- `blocks`: one row per block, including all scalar block fields
- `transactions`: one row per transaction, including all scalar transaction fields
- `transaction_inputs`: one row per vin entry
- `transaction_input_witness`: one row per witness stack item
- `transaction_outputs`: one row per vout entry
- `transaction_output_addresses`: one row per output address entry
- `sync_metadata`: stores sync progress and reorg bookkeeping

This design preserves queryability for analytics while keeping nested arrays normalized.

## 2. Syncing Bitcoin RPC into SQLite

The sync script is incremental and idempotent:

```powershell
python .\Homework-3\sync_bitcoin_to_sqlite.py --sqlite-db C:\absolute\path\bitcoin.sqlite --rpc-url http://127.0.0.1:8332 --rpc-user student --rpc-password your_password
```

If you have a cookie file instead:

```powershell
python .\Homework-3\sync_bitcoin_to_sqlite.py --sqlite-db C:\absolute\path\bitcoin.sqlite --rpc-cookie-file C:\absolute\path\.cookie
```

Useful options:

- `--start-height`
- `--stop-height`
- `--max-blocks`
- `--poll-interval-seconds`
- `--batch-size`
- `--sqlite-synchronous`

The script:

1. ensures the schema exists
2. checks for reorgs by comparing the local tip hash to the node's active chain
3. rolls back mismatched local blocks if needed
4. fetches each block with `getblockhash(height)` and `getblock(hash, 2)`
5. upserts blocks and transactions inside SQLite transactions

To keep the database current every few minutes, either:

- run the script continuously with `--poll-interval-seconds 300`
- or register the command in Windows Task Scheduler / cron and run it periodically

For faster catch-up while the node is far ahead of SQLite, use:

```powershell
python .\Homework-3\sync_bitcoin_to_sqlite.py --sqlite-db C:\absolute\path\bitcoin.sqlite --rpc-cookie-file C:\absolute\path\.cookie --batch-size 100 --sqlite-synchronous NORMAL --poll-interval-seconds 300
```

This batches both RPC fetches and SQLite commits. After the initial catch-up, you can switch back to `--sqlite-synchronous FULL` if you want the most conservative durability setting.

## 3. Checking the Last Downloaded Block

This helper uses the exact RPCs the assignment mentions:

```powershell
python .\Homework-3\bitcoin_sync_status.py --rpc-url http://127.0.0.1:8332 --rpc-user student --rpc-password your_password
```

It calls:

- `getblockchaininfo`
- `getblockcount`
- `getblock(bestblockhash, 2)`

If you also pass the SQLite database, it compares the node tip to the local SQL snapshot:

```powershell
python .\Homework-3\bitcoin_sync_status.py --sqlite-db C:\absolute\path\bitcoin.sqlite --rpc-url http://127.0.0.1:8332 --rpc-user student --rpc-password your_password
```

## 4. Natural Language to SQL

This script is the Homework 2 OpenAI file adapted for a live SQLite database:

```powershell
python .\Homework-3\bitcoin_text_to_sql.py --sqlite-db C:\absolute\path\bitcoin.sqlite --question "How many blocks are there?"
```

What it does:

1. validates the absolute database path
2. introspects the live SQLite schema from `sqlite_master`
3. concatenates the schema with the user's question
4. sends both to the OpenAI Chat Completions API
5. validates that the generated SQL is read-only
6. executes the SQL against SQLite in read-only mode and returns the answer

The script also supports explicit refusal by returning `CANNOT_ANSWER` when the question cannot be answered from the schema alone.

## 5. Bonus Auto-Schema Utility

This script generates a first-pass SQLite schema from a sample JSON object:

```powershell
python .\Homework-3\auto_schema_from_json.py --json-file C:\absolute\path\sample_getblock.json --root-table block_payload
```

This is intended as a 99%-solution helper, with small manual cleanup afterward.

## 6. Test Harness

Run the text-to-SQL tests like this:

```powershell
python .\Homework-3\run_text_to_sql_tests.py --sqlite-db C:\absolute\path\bitcoin.sqlite
```

This will:

1. execute each expected SQL statement to get the gold answer
2. ask the model to generate SQL from the natural-language question
3. execute the generated SQL
4. compare the generated answer to the gold answer
5. write a markdown report

The harness evaluates three groups:

- 13 standard answerable cases
- rejection cases that should return `CANNOT_ANSWER`
- 3 intentionally hard cases that expose model failure boundaries

## 7. Notes for the Assignment

- `getblockcount` gives the most-work fully validated chain height.
- `getblockchaininfo` gives both block count and header count, which is useful while syncing.
- The sync script is safe to rerun and is suitable for external scheduling every few minutes.
- The hard cases are included specifically to expose failure boundaries instead of pretending the system is perfect.
