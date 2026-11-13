-- One current judgement per stock and actual launch; ordinary edits use UPSERT.
CREATE TABLE research_theme_inputs (
    stock_id INTEGER NOT NULL REFERENCES stocks(id),
    first_board_date TEXT NOT NULL,
    main_theme TEXT NOT NULL,
    basis TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    attribute_overrides_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY(stock_id, first_board_date)
);
CREATE TABLE research_dependencies (
    record_key TEXT NOT NULL REFERENCES legacy_key_map(legacy_record_key),
    stock_id INTEGER NOT NULL REFERENCES stocks(id),
    first_board_date TEXT NOT NULL,
    PRIMARY KEY(record_key,stock_id,first_board_date)
);
CREATE INDEX research_dependency_subject ON research_dependencies(stock_id,first_board_date);
