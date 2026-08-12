# 竞价快照合同

当前历史同花顺涨停池只保存收盘后的封单事实，不能还原竞价过程。

这里仅接收两类记录：

- 当时实时保存的 `live_snapshot`；
- 来源明确、可以重复核验的 `historical_verified`。

禁止根据收盘结果或事后口述补造竞价数据。

`observations.jsonl` 每行字段：

- `observation_id`：稳定唯一标识。
- `date` / `information_cutoff`：交易日与信息截止日。
- `captured_at`：带时区的实际快照时间。
- `code` / `name`：股票身份。
- `source` / `source_mode`：来源和采集方式。
- `indicative_price`：当时竞价价格，可缺失但不得推算。
- `matched_amount`：当时已匹配金额，可缺失。
- `unmatched_limit_order_amount`：涨停价未匹配封单金额，可缺失。
- `note`：只写客观采集异常，不写强弱结论。

```powershell
python tools/auction_observations.py validate
python tools/auction_observations.py series 2025-11-07 002451
```

当前文件为空，代表历史竞价路径尚无可靠真相源；这比用收盘封单反推更安全。
