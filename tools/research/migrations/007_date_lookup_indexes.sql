-- Date-wide limit-pool lookups (high pools, one-word pools, trading calendar) were full scans.
CREATE INDEX IF NOT EXISTS idx_daily_market_source_date ON daily_market(source_type, trade_date, board_height);
CREATE INDEX IF NOT EXISTS idx_market_source_kind_stock ON market_source_facts(source_kind, stock_id, trade_date);
ANALYZE;
