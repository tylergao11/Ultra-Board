-- Foreign-key children and write-path lookups were unindexed (full scans on every check read and cascade).
CREATE INDEX IF NOT EXISTS idx_research_checks_static ON research_checks(static_research_id);
CREATE INDEX IF NOT EXISTS idx_research_checks_dynamic ON research_checks(dynamic_research_id);
CREATE INDEX IF NOT EXISTS idx_launch_rounds_stock_first ON launch_rounds(stock_id, first_board_date);
CREATE INDEX IF NOT EXISTS idx_first_open_events_round ON first_open_events(launch_round_id);
CREATE INDEX IF NOT EXISTS idx_static_research_event ON static_research(first_open_event_id);
CREATE INDEX IF NOT EXISTS idx_dynamic_research_event ON dynamic_research(first_open_event_id);
CREATE INDEX IF NOT EXISTS idx_write_requests_object ON write_requests(object_type, object_key);
ANALYZE;
