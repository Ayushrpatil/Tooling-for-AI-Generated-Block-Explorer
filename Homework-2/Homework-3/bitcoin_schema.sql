PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sync_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blocks (
    block_hash TEXT PRIMARY KEY,
    height INTEGER NOT NULL UNIQUE,
    confirmations INTEGER,
    size INTEGER NOT NULL,
    stripped_size INTEGER,
    weight INTEGER,
    version INTEGER NOT NULL,
    version_hex TEXT NOT NULL,
    merkle_root TEXT NOT NULL,
    block_time INTEGER NOT NULL,
    median_time INTEGER,
    nonce INTEGER NOT NULL,
    bits TEXT NOT NULL,
    difficulty REAL NOT NULL,
    chainwork TEXT NOT NULL,
    tx_count INTEGER NOT NULL,
    previous_block_hash TEXT,
    next_block_hash TEXT,
    raw_json TEXT NOT NULL,
    inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_blocks_height ON blocks(height);
CREATE INDEX IF NOT EXISTS idx_blocks_previous ON blocks(previous_block_hash);

CREATE TABLE IF NOT EXISTS transactions (
    txid TEXT PRIMARY KEY,
    block_hash TEXT NOT NULL REFERENCES blocks(block_hash) ON DELETE CASCADE,
    block_height INTEGER NOT NULL,
    tx_index INTEGER NOT NULL,
    in_active_chain INTEGER,
    hex TEXT,
    tx_hash TEXT NOT NULL,
    size INTEGER NOT NULL,
    vsize INTEGER NOT NULL,
    weight INTEGER NOT NULL,
    version INTEGER NOT NULL,
    locktime INTEGER NOT NULL,
    confirmations INTEGER,
    block_time INTEGER,
    time INTEGER,
    is_coinbase INTEGER NOT NULL,
    raw_json TEXT NOT NULL,
    inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(block_hash, tx_index)
);

CREATE INDEX IF NOT EXISTS idx_transactions_block_hash ON transactions(block_hash);
CREATE INDEX IF NOT EXISTS idx_transactions_block_height ON transactions(block_height);
CREATE INDEX IF NOT EXISTS idx_transactions_coinbase ON transactions(is_coinbase);

CREATE TABLE IF NOT EXISTS transaction_inputs (
    txid TEXT NOT NULL REFERENCES transactions(txid) ON DELETE CASCADE,
    vin_index INTEGER NOT NULL,
    coinbase TEXT,
    prev_txid TEXT,
    prev_vout INTEGER,
    script_sig_asm TEXT,
    script_sig_hex TEXT,
    sequence INTEGER NOT NULL,
    raw_json TEXT NOT NULL,
    inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (txid, vin_index)
);

CREATE INDEX IF NOT EXISTS idx_inputs_prevout ON transaction_inputs(prev_txid, prev_vout);

CREATE TABLE IF NOT EXISTS transaction_input_witness (
    txid TEXT NOT NULL,
    vin_index INTEGER NOT NULL,
    witness_index INTEGER NOT NULL,
    witness_hex TEXT NOT NULL,
    PRIMARY KEY (txid, vin_index, witness_index),
    FOREIGN KEY (txid, vin_index)
        REFERENCES transaction_inputs(txid, vin_index)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transaction_outputs (
    txid TEXT NOT NULL REFERENCES transactions(txid) ON DELETE CASCADE,
    vout_index INTEGER NOT NULL,
    value_btc_text TEXT NOT NULL,
    value_sats INTEGER NOT NULL,
    script_pubkey_asm TEXT,
    script_pubkey_hex TEXT,
    script_pubkey_req_sigs INTEGER,
    script_pubkey_type TEXT,
    raw_json TEXT NOT NULL,
    inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (txid, vout_index)
);

CREATE INDEX IF NOT EXISTS idx_outputs_value_sats ON transaction_outputs(value_sats);
CREATE INDEX IF NOT EXISTS idx_outputs_script_type ON transaction_outputs(script_pubkey_type);

CREATE TABLE IF NOT EXISTS transaction_output_addresses (
    txid TEXT NOT NULL,
    vout_index INTEGER NOT NULL,
    address_index INTEGER NOT NULL,
    address TEXT NOT NULL,
    PRIMARY KEY (txid, vout_index, address_index),
    FOREIGN KEY (txid, vout_index)
        REFERENCES transaction_outputs(txid, vout_index)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_output_addresses_address ON transaction_output_addresses(address);
