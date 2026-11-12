# 研究库数据字典

统一约定：时区为 Asia/Shanghai；日期为 ISO `YYYY-MM-DD`；时间保留来源精度；价格以千分之一元整数保存；比例以百万分之一保存；NULL 表示源资料没有该值，显式 false 与空字符串保留在原文 JSON。

## announcements

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| stock_id | INTEGER | 0 | 0 |
| stock_name | TEXT | 0 | 0 |
| disclosure_time | TEXT | 0 | 0 |
| related_trade_date | TEXT | 0 | 0 |
| title | TEXT | 0 | 0 |
| capital_matter_type | TEXT | 0 | 0 |
| pollution_result | INTEGER | 0 | 0 |
| basis | TEXT | 1 | 0 |
| evidence_file_id | INTEGER | 0 | 0 |
| source_record_id | INTEGER | 0 | 0 |
| raw_json | TEXT | 1 | 0 |

## archived_sections

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| source_file | TEXT | 1 | 0 |
| section | TEXT | 1 | 0 |
| archive_kind | TEXT | 1 | 0 |
| raw_sha256 | TEXT | 1 | 0 |
| raw_json | TEXT | 1 | 0 |

## concept_merges

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| source_label | TEXT | 1 | 0 |
| unified_label | TEXT | 1 | 0 |
| rule_set_id | INTEGER | 1 | 0 |
| scope | TEXT | 1 | 0 |
| rationale | TEXT | 1 | 0 |

## concepts

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| source_code | TEXT | 0 | 0 |
| source_name | TEXT | 1 | 0 |
| unified_name | TEXT | 1 | 0 |

## daily_market

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| stock_id | INTEGER | 1 | 0 |
| trade_date | TEXT | 1 | 0 |
| source_type | TEXT | 1 | 0 |
| price_mode | TEXT | 1 | 0 |
| open_milli | INTEGER | 0 | 0 |
| high_milli | INTEGER | 0 | 0 |
| low_milli | INTEGER | 0 | 0 |
| close_milli | INTEGER | 0 | 0 |
| previous_close_milli | INTEGER | 0 | 0 |
| limit_up_milli | INTEGER | 0 | 0 |
| limit_down_milli | INTEGER | 0 | 0 |
| board_height | INTEGER | 0 | 0 |
| first_limit_time | TEXT | 0 | 0 |
| strict_one_word | INTEGER | 0 | 0 |
| evidence_file_id | INTEGER | 0 | 0 |
| raw_json | TEXT | 1 | 0 |

## dynamic_research

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| first_open_event_id | INTEGER | 1 | 0 |
| plan_id | INTEGER | 1 | 0 |
| legacy_record_key | TEXT | 1 | 0 |
| version | INTEGER | 1 | 0 |
| is_current | INTEGER | 1 | 0 |
| research_status | TEXT | 1 | 0 |
| confirmation_status | TEXT | 1 | 0 |
| auction_result | TEXT | 0 | 0 |
| auction_pct_micros | INTEGER | 0 | 0 |
| pk_result | TEXT | 0 | 0 |
| buy_result | TEXT | 0 | 0 |
| buy_type | TEXT | 0 | 0 |
| buy_time | TEXT | 0 | 0 |
| buy_price_milli | INTEGER | 0 | 0 |
| sell_time | TEXT | 0 | 0 |
| sell_price_milli | INTEGER | 0 | 0 |
| return_pct_micros | INTEGER | 0 | 0 |
| source_record_id | INTEGER | 1 | 0 |
| evidence_snapshot_json | TEXT | 1 | 0 |
| raw_json | TEXT | 1 | 0 |
| rule_set_id | INTEGER | 0 | 0 |

## evidence_contents

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| sha256 | TEXT | 1 | 0 |
| size_bytes | INTEGER | 1 | 0 |

## evidence_files

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| path | TEXT | 1 | 0 |
| content_id | INTEGER | 1 | 0 |
| category | TEXT | 1 | 0 |
| source_date | TEXT | 0 | 0 |
| captured_at | TEXT | 0 | 0 |
| modified_at | TEXT | 1 | 0 |
| parse_status | TEXT | 1 | 0 |
| parse_error | TEXT | 0 | 0 |

## field_mappings

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| source_file | TEXT | 1 | 0 |
| section | TEXT | 1 | 0 |
| field_path | TEXT | 1 | 0 |
| occurrences | INTEGER | 1 | 0 |
| value_types | TEXT | 1 | 0 |
| target_object | TEXT | 1 | 0 |
| treatment | TEXT | 1 | 0 |
| example_json | TEXT | 0 | 0 |

## first_open_events

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| launch_round_id | INTEGER | 1 | 0 |
| one_word_run_id | INTEGER | 0 | 0 |
| event_date | TEXT | 0 | 0 |
| event_status | TEXT | 1 | 0 |
| legacy_record_key | TEXT | 1 | 0 |
| raw_json | TEXT | 1 | 0 |

## generation_batches

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| generation_key | TEXT | 1 | 0 |
| created_at | TEXT | 1 | 0 |
| database_sha256 | TEXT | 1 | 0 |
| input_batch_key | TEXT | 1 | 0 |
| rule_versions_json | TEXT | 1 | 0 |
| output_dir | TEXT | 1 | 0 |
| manifest_json | TEXT | 1 | 0 |

## import_batches

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| batch_key | TEXT | 1 | 0 |
| kind | TEXT | 1 | 0 |
| started_at | TEXT | 1 | 0 |
| completed_at | TEXT | 0 | 0 |
| status | TEXT | 1 | 0 |
| input_manifest_hash | TEXT | 0 | 0 |
| summary_json | TEXT | 1 | 0 |

## intraday_events

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| stock_id | INTEGER | 1 | 0 |
| trade_date | TEXT | 1 | 0 |
| event_type | TEXT | 1 | 0 |
| event_time | TEXT | 0 | 0 |
| time_precision | TEXT | 1 | 0 |
| value_json | TEXT | 1 | 0 |
| evidence_file_id | INTEGER | 0 | 0 |

## issues

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| scope | TEXT | 1 | 0 |
| object_key | TEXT | 0 | 0 |
| issue_kind | TEXT | 1 | 0 |
| severity | TEXT | 1 | 0 |
| detail | TEXT | 1 | 0 |
| impact | TEXT | 1 | 0 |
| status | TEXT | 1 | 0 |

## launch_rounds

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| stock_id | INTEGER | 1 | 0 |
| legacy_record_key | TEXT | 1 | 0 |
| first_board_date | TEXT | 0 | 0 |
| focus_date | TEXT | 1 | 0 |
| board_sequence_text | TEXT | 0 | 0 |
| confirmed_main_theme | TEXT | 0 | 0 |
| confirmation_status | TEXT | 1 | 0 |
| source_record_id | INTEGER | 1 | 0 |
| raw_json | TEXT | 1 | 0 |

## legacy_key_map

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| legacy_record_key | TEXT | 0 | 1 |
| stock_id | INTEGER | 1 | 0 |
| launch_round_id | INTEGER | 1 | 0 |
| first_open_event_id | INTEGER | 1 | 0 |
| static_source_record_id | INTEGER | 1 | 0 |
| dynamic_source_record_id | INTEGER | 0 | 0 |

## market_source_facts

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| fact_type | TEXT | 1 | 0 |
| source_kind | TEXT | 1 | 0 |
| trade_date | TEXT | 0 | 0 |
| stock_id | INTEGER | 0 | 0 |
| stock_code | TEXT | 0 | 0 |
| stock_name | TEXT | 0 | 0 |
| sector_code | TEXT | 0 | 0 |
| sector_name | TEXT | 0 | 0 |
| topic | TEXT | 0 | 0 |
| topic_tags | TEXT | 0 | 0 |
| description | TEXT | 0 | 0 |
| board_height | INTEGER | 0 | 0 |
| event_time | TEXT | 0 | 0 |
| event_datetime | TEXT | 0 | 0 |
| evidence_file_id | INTEGER | 0 | 0 |
| raw_location | TEXT | 1 | 0 |
| raw_json | TEXT | 1 | 0 |

## one_word_runs

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| launch_round_id | INTEGER | 1 | 0 |
| start_date | TEXT | 0 | 0 |
| end_date | TEXT | 0 | 0 |
| status | TEXT | 1 | 0 |
| raw_json | TEXT | 1 | 0 |

## plate_memberships

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| plate_code | TEXT | 1 | 0 |
| plate_name | TEXT | 0 | 0 |
| trade_date | TEXT | 1 | 0 |
| stock_id | INTEGER | 1 | 0 |
| stock_name | TEXT | 0 | 0 |
| evidence_file_id | INTEGER | 0 | 0 |

## pool_members

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| pool_id | INTEGER | 1 | 0 |
| stock_id | INTEGER | 1 | 0 |
| board_height | INTEGER | 0 | 0 |
| member_status | TEXT | 0 | 0 |
| query_direction | TEXT | 0 | 0 |
| source_record_id | INTEGER | 0 | 0 |
| evidence_file_id | INTEGER | 0 | 0 |
| raw_json | TEXT | 1 | 0 |

## research_checks

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| static_research_id | INTEGER | 0 | 0 |
| dynamic_research_id | INTEGER | 0 | 0 |
| check_type | TEXT | 1 | 0 |
| subject_stock_id | INTEGER | 0 | 0 |
| outcome | TEXT | 0 | 0 |
| basis | TEXT | 0 | 0 |
| source_json | TEXT | 1 | 0 |
| raw_json | TEXT | 1 | 0 |

## research_plans

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| plan_code | TEXT | 1 | 0 |
| version | INTEGER | 1 | 0 |
| name | TEXT | 1 | 0 |
| status | TEXT | 1 | 0 |
| definition_json | TEXT | 1 | 0 |
| rule_set_id | INTEGER | 1 | 0 |

## revisions

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| object_type | TEXT | 1 | 0 |
| object_key | TEXT | 1 | 0 |
| version | INTEGER | 1 | 0 |
| change_json | TEXT | 1 | 0 |
| confirmation_status | TEXT | 1 | 0 |
| source_record_id | INTEGER | 0 | 0 |
| created_at | TEXT | 1 | 0 |

## rule_items

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| rule_set_id | INTEGER | 1 | 0 |
| section | TEXT | 1 | 0 |
| sequence_no | INTEGER | 1 | 0 |
| text_value | TEXT | 0 | 0 |
| raw_json | TEXT | 1 | 0 |

## rule_sets

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| rule_type | TEXT | 1 | 0 |
| version | TEXT | 1 | 0 |
| status | TEXT | 1 | 0 |
| source_path | TEXT | 1 | 0 |
| source_sha256 | TEXT | 1 | 0 |
| effective_from | TEXT | 0 | 0 |
| created_at | TEXT | 1 | 0 |

## schema_migrations

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| version | INTEGER | 0 | 1 |
| name | TEXT | 1 | 0 |
| checksum | TEXT | 1 | 0 |
| applied_at | TEXT | 1 | 0 |

## source_records

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| batch_id | INTEGER | 1 | 0 |
| source_kind | TEXT | 1 | 0 |
| source_path | TEXT | 1 | 0 |
| section | TEXT | 1 | 0 |
| record_key | TEXT | 1 | 0 |
| stock_code | TEXT | 0 | 0 |
| effective_date | TEXT | 0 | 0 |
| raw_sha256 | TEXT | 1 | 0 |
| raw_json | TEXT | 1 | 0 |

## static_research

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| first_open_event_id | INTEGER | 1 | 0 |
| legacy_record_key | TEXT | 1 | 0 |
| version | INTEGER | 1 | 0 |
| is_current | INTEGER | 1 | 0 |
| research_status | TEXT | 1 | 0 |
| confirmation_status | TEXT | 1 | 0 |
| main_theme | TEXT | 0 | 0 |
| replenishment_result | TEXT | 0 | 0 |
| suppression_result | TEXT | 0 | 0 |
| announcement_pollution | INTEGER | 0 | 0 |
| mapping_basis | TEXT | 0 | 0 |
| suppression_basis | TEXT | 0 | 0 |
| announcement_basis | TEXT | 0 | 0 |
| source_record_id | INTEGER | 1 | 0 |
| rule_set_id | INTEGER | 1 | 0 |
| evidence_snapshot_json | TEXT | 1 | 0 |
| raw_json | TEXT | 1 | 0 |

## statistics

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| generation_id | INTEGER | 1 | 0 |
| plan_id | INTEGER | 0 | 0 |
| metric_key | TEXT | 1 | 0 |
| metric_value | TEXT | 0 | 0 |
| numerator | INTEGER | 0 | 0 |
| denominator | INTEGER | 0 | 0 |
| raw_json | TEXT | 1 | 0 |

## stock_concepts

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| stock_id | INTEGER | 1 | 0 |
| concept_id | INTEGER | 1 | 0 |
| observed_date | TEXT | 1 | 0 |
| captured_date | TEXT | 0 | 0 |
| applies_from | TEXT | 0 | 0 |
| applies_to | TEXT | 0 | 0 |
| historical_status | TEXT | 1 | 0 |
| analysis | TEXT | 0 | 0 |
| evidence_file_id | INTEGER | 0 | 0 |

## stock_names

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| stock_id | INTEGER | 1 | 0 |
| name | TEXT | 1 | 0 |
| valid_from | TEXT | 0 | 0 |
| valid_to | TEXT | 0 | 0 |
| source_record_id | INTEGER | 0 | 0 |

## stock_pools

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| pool_type | TEXT | 1 | 0 |
| pool_date | TEXT | 1 | 0 |
| rule_set_id | INTEGER | 0 | 0 |
| candidate_event_id | INTEGER | 0 | 0 |
| input_version | TEXT | 1 | 0 |
| coverage_status | TEXT | 1 | 0 |
| source_kind | TEXT | 1 | 0 |

## stocks

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| code | TEXT | 1 | 0 |
| market | TEXT | 1 | 0 |
| created_at | TEXT | 1 | 0 |

## store_meta

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| key | TEXT | 0 | 1 |
| value | TEXT | 1 | 0 |

## trade_outcomes

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| id | INTEGER | 0 | 1 |
| dynamic_research_id | INTEGER | 1 | 0 |
| bought | INTEGER | 0 | 0 |
| buy_day_sealed | INTEGER | 0 | 0 |
| next_day_board | INTEGER | 0 | 0 |
| next_day_low_open | INTEGER | 0 | 0 |
| next_day_limit_down | INTEGER | 0 | 0 |
| consecutive_boards | INTEGER | 0 | 0 |
| sell_date | TEXT | 0 | 0 |
| return_pct_micros | INTEGER | 0 | 0 |
| raw_json | TEXT | 1 | 0 |

## trading_days

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| trade_date | TEXT | 0 | 1 |
| is_trading_day | INTEGER | 1 | 0 |
| calendar_source | TEXT | 1 | 0 |
| raw_market_coverage | INTEGER | 1 | 0 |
| price_coverage | INTEGER | 1 | 0 |
| note | TEXT | 0 | 0 |

## write_requests

| 字段 | 类型 | 非空 | 主键 |
| --- | --- | --- | --- |
| request_id | TEXT | 0 | 1 |
| object_type | TEXT | 1 | 0 |
| object_key | TEXT | 1 | 0 |
| request_sha256 | TEXT | 1 | 0 |
| result_json | TEXT | 1 | 0 |
| created_at | TEXT | 1 | 0 |
