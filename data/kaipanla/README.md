# 客观行情事实缓存

`data/kaipanla/` 不再是题材真相源。这里保留采集所得的板数、OHLC、封板时间等客观事实，供同花顺节点入口做价格与连板结构计算。

## 结构

```text
data/kaipanla/
  device_id.txt
  backfill_state.json
  ohlc_cache/
  raw/YYYY-MM-DD/
    zt_pool.json       # 板数、代码、名称及挂载后的 OHLC 等客观事实
    ohlc.json          # 二板及以上 OHLC 补全证据
    ths_limit_pool.json# 同花顺首封、终封与炸板次数
    sentiment.json     # 原始情绪快照，节点模型不读取其题材
    expression.json    # 原始表达快照，节点模型不读取其题材
    sector_ladder.json # 遗留原始分类快照，禁止进入节点与模型判断
```

## 使用边界

- 唯一题材、公告身份和风口排名真相是 `data/ths/strong_wind/YYYY-MM-DD.json`。
- `zt_pool.json` 中即使仍保留历史 `theme`、`raw` 或 `sector_code`，也只属于原始采集记录；正式读侧禁止访问这些字段。
- 节点入口对白名单字段取值：`code`、`boards`、`open`、`high`、`low`。股票名称和主分组采用同花顺日文件。
- 真一字只认同一价格口径下 `open == high == low`；T 字、开板回封、高开快速封板都不是一字锚。
- 二板及以上缺少板数或 OHLC 时直接失败，不以封板时间、开盘涨停或默认值替代。
- 本目录不再产生梯队日录、公告分类表或任何题材派生结果。

采集命令：

```powershell
python -m ultraboard.kaipanla.backfill
python -m ultraboard.kaipanla.ohlc
python -m ultraboard.kaipanla.ths_limit_pool 2026-08-06
```
