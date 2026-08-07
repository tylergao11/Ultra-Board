# 开盘啦原始数据源

`data/kaipanla/` 是个股具体题材分类的唯一真相源。这里只保存开盘啦接口原文与无判断的结构化快照，不保存节点、买点、评分或人工结果。

## 日目录

```text
data/kaipanla/raw/YYYY-MM-DD/
  zt_pool.json        # 涨停股、主分类 theme、全部具体分类原文 raw[12]
  sector_ladder.json # 开盘啦题材梯队原始快照
  sentiment.json     # 当日情绪原始响应
  expression.json    # 当日梯队表达原始响应
  plate_info.json    # 仅在来源确属当日时保存的详细解释，可选
  _DONE              # 当日开盘啦必需接口已闭合
```

具体分类合同：

- `zt_pool.json/stocks[].theme` 是开盘啦主分类。
- `zt_pool.json/stocks[].raw[12]` 是开盘啦全部具体分类原文。
- `sector_ladder.json` 保留开盘啦板块、梯队与源顺序，不把顺序直接解释成交易结论。
- 禁止使用同花顺标题、个股事件文字或人工关键词覆盖这些分类。

本目录不再混放第三方 OHLC、同花顺涨停池副本、人工证据或历史模型产物。

## 入口

```powershell
python -m ultraboard.kaipanla.backfill --start 2026-08-07 --end 2026-08-07
python -c "from ultraboard.kaipanla import load_day; print(load_day('2026-08-06')['provider'])"
```
