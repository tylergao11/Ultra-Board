PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY,
    batch_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    input_manifest_hash TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS evidence_contents (
    id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    content_id INTEGER NOT NULL REFERENCES evidence_contents(id),
    category TEXT NOT NULL,
    source_date TEXT,
    captured_at TEXT,
    modified_at TEXT NOT NULL,
    parse_status TEXT NOT NULL DEFAULT 'indexed',
    parse_error TEXT,
    UNIQUE(path, content_id)
);
CREATE INDEX IF NOT EXISTS idx_evidence_path ON evidence_files(path);
CREATE INDEX IF NOT EXISTS idx_evidence_category_date ON evidence_files(category, source_date);

CREATE TABLE IF NOT EXISTS source_records (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES import_batches(id),
    source_kind TEXT NOT NULL,
    source_path TEXT NOT NULL,
    section TEXT NOT NULL,
    record_key TEXT NOT NULL,
    stock_code TEXT,
    effective_date TEXT,
    raw_sha256 TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    UNIQUE(source_kind, section, record_key, raw_sha256)
);
CREATE INDEX IF NOT EXISTS idx_source_records_key ON source_records(record_key);

CREATE TABLE IF NOT EXISTS field_mappings (
    id INTEGER PRIMARY KEY,
    source_file TEXT NOT NULL,
    section TEXT NOT NULL,
    field_path TEXT NOT NULL,
    occurrences INTEGER NOT NULL,
    value_types TEXT NOT NULL,
    target_object TEXT NOT NULL,
    treatment TEXT NOT NULL,
    example_json TEXT,
    UNIQUE(source_file, section, field_path)
);

CREATE TABLE IF NOT EXISTS rule_sets (
    id INTEGER PRIMARY KEY,
    rule_type TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    effective_from TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(rule_type, version)
);

CREATE TABLE IF NOT EXISTS rule_items (
    id INTEGER PRIMARY KEY,
    rule_set_id INTEGER NOT NULL REFERENCES rule_sets(id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    text_value TEXT,
    raw_json TEXT NOT NULL,
    UNIQUE(rule_set_id, section, sequence_no)
);

CREATE TABLE IF NOT EXISTS stocks (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    market TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stock_names (
    id INTEGER PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    source_record_id INTEGER REFERENCES source_records(id),
    UNIQUE(stock_id, name, valid_from)
);

CREATE TABLE IF NOT EXISTS trading_days (
    trade_date TEXT PRIMARY KEY,
    is_trading_day INTEGER NOT NULL CHECK(is_trading_day IN (0, 1)),
    calendar_source TEXT NOT NULL,
    raw_market_coverage INTEGER NOT NULL DEFAULT 0,
    price_coverage INTEGER NOT NULL DEFAULT 0,
    note TEXT
);

CREATE TABLE IF NOT EXISTS concepts (
    id INTEGER PRIMARY KEY,
    source_code TEXT,
    source_name TEXT NOT NULL,
    unified_name TEXT NOT NULL,
    UNIQUE(source_code, source_name)
);

CREATE TABLE IF NOT EXISTS concept_merges (
    id INTEGER PRIMARY KEY,
    source_label TEXT NOT NULL,
    unified_label TEXT NOT NULL,
    rule_set_id INTEGER NOT NULL REFERENCES rule_sets(id),
    scope TEXT NOT NULL,
    rationale TEXT NOT NULL,
    UNIQUE(source_label, unified_label, rule_set_id, scope)
);

CREATE TABLE IF NOT EXISTS stock_concepts (
    id INTEGER PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
    concept_id INTEGER NOT NULL REFERENCES concepts(id),
    observed_date TEXT NOT NULL,
    captured_date TEXT,
    applies_from TEXT,
    applies_to TEXT,
    historical_status TEXT NOT NULL,
    analysis TEXT,
    evidence_file_id INTEGER REFERENCES evidence_files(id),
    UNIQUE(stock_id, concept_id, observed_date, evidence_file_id)
);
CREATE INDEX IF NOT EXISTS idx_stock_concepts_lookup ON stock_concepts(stock_id, observed_date);

CREATE TABLE IF NOT EXISTS plate_memberships (
    id INTEGER PRIMARY KEY,
    plate_code TEXT NOT NULL,
    plate_name TEXT,
    trade_date TEXT NOT NULL,
    stock_id INTEGER NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
    stock_name TEXT,
    evidence_file_id INTEGER REFERENCES evidence_files(id),
    UNIQUE(plate_code, trade_date, stock_id, evidence_file_id)
);
CREATE INDEX IF NOT EXISTS idx_plate_members_stock_date ON plate_memberships(stock_id, trade_date);

CREATE TABLE IF NOT EXISTS daily_market (
    id INTEGER PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
    trade_date TEXT NOT NULL,
    source_type TEXT NOT NULL,
    price_mode TEXT NOT NULL DEFAULT 'unadjusted',
    open_milli INTEGER,
    high_milli INTEGER,
    low_milli INTEGER,
    close_milli INTEGER,
    previous_close_milli INTEGER,
    limit_up_milli INTEGER,
    limit_down_milli INTEGER,
    board_height INTEGER,
    first_limit_time TEXT,
    strict_one_word INTEGER,
    evidence_file_id INTEGER REFERENCES evidence_files(id),
    raw_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(stock_id, trade_date, source_type, evidence_file_id)
);
CREATE INDEX IF NOT EXISTS idx_daily_market_lookup ON daily_market(stock_id, trade_date);

CREATE TABLE IF NOT EXISTS intraday_events (
    id INTEGER PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
    trade_date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_time TEXT,
    time_precision TEXT NOT NULL,
    value_json TEXT NOT NULL DEFAULT '{}',
    evidence_file_id INTEGER REFERENCES evidence_files(id),
    UNIQUE(stock_id, trade_date, event_type, event_time, evidence_file_id)
);

CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY,
    stock_id INTEGER REFERENCES stocks(id),
    stock_name TEXT,
    disclosure_time TEXT,
    related_trade_date TEXT,
    title TEXT,
    capital_matter_type TEXT,
    pollution_result INTEGER,
    basis TEXT NOT NULL,
    evidence_file_id INTEGER REFERENCES evidence_files(id),
    source_record_id INTEGER REFERENCES source_records(id),
    raw_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_announcements_stock_date ON announcements(stock_id, related_trade_date);

CREATE TABLE IF NOT EXISTS launch_rounds (
    id INTEGER PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
    legacy_record_key TEXT NOT NULL UNIQUE,
    first_board_date TEXT,
    focus_date TEXT NOT NULL,
    board_sequence_text TEXT,
    confirmed_main_theme TEXT,
    confirmation_status TEXT NOT NULL,
    source_record_id INTEGER NOT NULL REFERENCES source_records(id),
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS one_word_runs (
    id INTEGER PRIMARY KEY,
    launch_round_id INTEGER NOT NULL REFERENCES launch_rounds(id) ON DELETE CASCADE,
    start_date TEXT,
    end_date TEXT,
    status TEXT NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(launch_round_id, start_date, end_date)
);

CREATE TABLE IF NOT EXISTS first_open_events (
    id INTEGER PRIMARY KEY,
    launch_round_id INTEGER NOT NULL REFERENCES launch_rounds(id) ON DELETE CASCADE,
    one_word_run_id INTEGER REFERENCES one_word_runs(id),
    event_date TEXT,
    event_status TEXT NOT NULL,
    legacy_record_key TEXT NOT NULL UNIQUE,
    raw_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_first_open_date ON first_open_events(event_date);

CREATE TABLE IF NOT EXISTS legacy_key_map (
    legacy_record_key TEXT PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id),
    launch_round_id INTEGER NOT NULL REFERENCES launch_rounds(id),
    first_open_event_id INTEGER NOT NULL REFERENCES first_open_events(id),
    static_source_record_id INTEGER NOT NULL REFERENCES source_records(id),
    dynamic_source_record_id INTEGER REFERENCES source_records(id)
);

CREATE TABLE IF NOT EXISTS stock_pools (
    id INTEGER PRIMARY KEY,
    pool_type TEXT NOT NULL,
    pool_date TEXT NOT NULL,
    rule_set_id INTEGER REFERENCES rule_sets(id),
    candidate_event_id INTEGER REFERENCES first_open_events(id),
    input_version TEXT NOT NULL,
    coverage_status TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    UNIQUE(pool_type, pool_date, rule_set_id, candidate_event_id, input_version, source_kind)
);

CREATE TABLE IF NOT EXISTS pool_members (
    id INTEGER PRIMARY KEY,
    pool_id INTEGER NOT NULL REFERENCES stock_pools(id) ON DELETE CASCADE,
    stock_id INTEGER NOT NULL REFERENCES stocks(id),
    board_height INTEGER,
    member_status TEXT,
    query_direction TEXT,
    source_record_id INTEGER REFERENCES source_records(id),
    evidence_file_id INTEGER REFERENCES evidence_files(id),
    raw_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(pool_id, stock_id, member_status, source_record_id, evidence_file_id)
);
CREATE INDEX IF NOT EXISTS idx_pool_lookup ON stock_pools(pool_type, pool_date);

CREATE TABLE IF NOT EXISTS static_research (
    id INTEGER PRIMARY KEY,
    first_open_event_id INTEGER NOT NULL REFERENCES first_open_events(id) ON DELETE CASCADE,
    legacy_record_key TEXT NOT NULL,
    version INTEGER NOT NULL,
    is_current INTEGER NOT NULL CHECK(is_current IN (0, 1)),
    research_status TEXT NOT NULL,
    confirmation_status TEXT NOT NULL,
    main_theme TEXT,
    replenishment_result TEXT,
    suppression_result TEXT,
    announcement_pollution INTEGER,
    mapping_basis TEXT,
    suppression_basis TEXT,
    announcement_basis TEXT,
    source_record_id INTEGER NOT NULL REFERENCES source_records(id),
    rule_set_id INTEGER NOT NULL REFERENCES rule_sets(id),
    evidence_snapshot_json TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    UNIQUE(legacy_record_key, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_static_current ON static_research(legacy_record_key) WHERE is_current = 1;

CREATE TABLE IF NOT EXISTS research_checks (
    id INTEGER PRIMARY KEY,
    static_research_id INTEGER REFERENCES static_research(id) ON DELETE CASCADE,
    dynamic_research_id INTEGER,
    check_type TEXT NOT NULL,
    subject_stock_id INTEGER REFERENCES stocks(id),
    outcome TEXT,
    basis TEXT,
    source_json TEXT NOT NULL DEFAULT '[]',
    raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS research_plans (
    id INTEGER PRIMARY KEY,
    plan_code TEXT NOT NULL,
    version INTEGER NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    rule_set_id INTEGER NOT NULL REFERENCES rule_sets(id),
    UNIQUE(plan_code, version)
);

CREATE TABLE IF NOT EXISTS dynamic_research (
    id INTEGER PRIMARY KEY,
    first_open_event_id INTEGER NOT NULL REFERENCES first_open_events(id) ON DELETE CASCADE,
    plan_id INTEGER NOT NULL REFERENCES research_plans(id),
    legacy_record_key TEXT NOT NULL,
    version INTEGER NOT NULL,
    is_current INTEGER NOT NULL CHECK(is_current IN (0, 1)),
    research_status TEXT NOT NULL,
    confirmation_status TEXT NOT NULL,
    auction_result TEXT,
    auction_pct_micros INTEGER,
    pk_result TEXT,
    buy_result TEXT,
    buy_type TEXT,
    buy_time TEXT,
    buy_price_milli INTEGER,
    sell_time TEXT,
    sell_price_milli INTEGER,
    return_pct_micros INTEGER,
    source_record_id INTEGER NOT NULL REFERENCES source_records(id),
    evidence_snapshot_json TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    UNIQUE(legacy_record_key, plan_id, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dynamic_current ON dynamic_research(legacy_record_key, plan_id) WHERE is_current = 1;

CREATE TABLE IF NOT EXISTS trade_outcomes (
    id INTEGER PRIMARY KEY,
    dynamic_research_id INTEGER NOT NULL REFERENCES dynamic_research(id) ON DELETE CASCADE,
    bought INTEGER,
    buy_day_sealed INTEGER,
    next_day_board INTEGER,
    next_day_low_open INTEGER,
    next_day_limit_down INTEGER,
    consecutive_boards INTEGER,
    sell_date TEXT,
    return_pct_micros INTEGER,
    raw_json TEXT NOT NULL,
    UNIQUE(dynamic_research_id)
);

CREATE TABLE IF NOT EXISTS revisions (
    id INTEGER PRIMARY KEY,
    object_type TEXT NOT NULL,
    object_key TEXT NOT NULL,
    version INTEGER NOT NULL,
    change_json TEXT NOT NULL,
    confirmation_status TEXT NOT NULL,
    source_record_id INTEGER REFERENCES source_records(id),
    created_at TEXT NOT NULL,
    UNIQUE(object_type, object_key, version)
);

CREATE TABLE IF NOT EXISTS archived_sections (
    id INTEGER PRIMARY KEY,
    source_file TEXT NOT NULL,
    section TEXT NOT NULL,
    archive_kind TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    UNIQUE(source_file, section, raw_sha256)
);

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY,
    scope TEXT NOT NULL,
    object_key TEXT,
    issue_kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    detail TEXT NOT NULL,
    impact TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    UNIQUE(scope, object_key, issue_kind, detail)
);

CREATE TABLE IF NOT EXISTS generation_batches (
    id INTEGER PRIMARY KEY,
    generation_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    database_sha256 TEXT NOT NULL,
    input_batch_key TEXT NOT NULL,
    rule_versions_json TEXT NOT NULL,
    output_dir TEXT NOT NULL,
    manifest_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS statistics (
    id INTEGER PRIMARY KEY,
    generation_id INTEGER NOT NULL REFERENCES generation_batches(id) ON DELETE CASCADE,
    plan_id INTEGER REFERENCES research_plans(id),
    metric_key TEXT NOT NULL,
    metric_value TEXT,
    numerator INTEGER,
    denominator INTEGER,
    raw_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(generation_id, plan_id, metric_key)
);

CREATE TABLE IF NOT EXISTS write_requests (
    request_id TEXT PRIMARY KEY,
    object_type TEXT NOT NULL,
    object_key TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE VIEW IF NOT EXISTS current_static_research AS
SELECT * FROM static_research WHERE is_current = 1;

CREATE VIEW IF NOT EXISTS current_dynamic_research AS
SELECT * FROM dynamic_research WHERE is_current = 1;

CREATE VIEW IF NOT EXISTS stock_current_names AS
SELECT s.id AS stock_id, s.code,
       COALESCE((SELECT sn.name FROM stock_names sn WHERE sn.stock_id=s.id ORDER BY COALESCE(sn.valid_from, '') DESC, sn.id DESC LIMIT 1), s.code) AS name
FROM stocks s;
