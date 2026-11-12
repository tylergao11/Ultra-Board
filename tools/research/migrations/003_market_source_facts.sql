CREATE TABLE IF NOT EXISTS market_source_facts (
    id INTEGER PRIMARY KEY,
    fact_type TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    trade_date TEXT,
    stock_id INTEGER REFERENCES stocks(id),
    stock_code TEXT,
    stock_name TEXT,
    sector_code TEXT,
    sector_name TEXT,
    topic TEXT,
    topic_tags TEXT,
    description TEXT,
    board_height INTEGER,
    event_time TEXT,
    event_datetime TEXT,
    evidence_file_id INTEGER REFERENCES evidence_files(id),
    raw_location TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    UNIQUE(fact_type, source_kind, evidence_file_id, raw_location)
);

CREATE INDEX IF NOT EXISTS idx_market_source_stock_date
ON market_source_facts(stock_id, trade_date, fact_type);

CREATE INDEX IF NOT EXISTS idx_market_source_sector_date
ON market_source_facts(sector_code, trade_date, fact_type);
