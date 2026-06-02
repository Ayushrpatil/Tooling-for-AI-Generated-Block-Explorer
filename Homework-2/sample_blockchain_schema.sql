CREATE TABLE blocks (
    block_hash TEXT PRIMARY KEY,
    height INTEGER NOT NULL UNIQUE,
    mined_at TIMESTAMP NOT NULL,
    transaction_count INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    miner TEXT,
    previous_block_hash TEXT
);

CREATE TABLE transactions (
    txid TEXT PRIMARY KEY,
    block_hash TEXT NOT NULL REFERENCES blocks(block_hash),
    fee_sats BIGINT NOT NULL,
    total_output_sats BIGINT NOT NULL,
    input_count INTEGER NOT NULL,
    output_count INTEGER NOT NULL,
    is_coinbase BOOLEAN NOT NULL
);

CREATE TABLE addresses (
    address TEXT PRIMARY KEY,
    first_seen_block_hash TEXT REFERENCES blocks(block_hash),
    balance_sats BIGINT NOT NULL
);

CREATE TABLE transaction_outputs (
    txid TEXT NOT NULL REFERENCES transactions(txid),
    output_index INTEGER NOT NULL,
    address TEXT REFERENCES addresses(address),
    value_sats BIGINT NOT NULL,
    spent BOOLEAN NOT NULL,
    PRIMARY KEY (txid, output_index)
);

CREATE TABLE transaction_inputs (
    txid TEXT NOT NULL REFERENCES transactions(txid),
    input_index INTEGER NOT NULL,
    previous_txid TEXT,
    previous_output_index INTEGER,
    source_address TEXT REFERENCES addresses(address),
    value_sats BIGINT NOT NULL,
    PRIMARY KEY (txid, input_index)
);
