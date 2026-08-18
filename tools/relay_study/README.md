# 连板接力研究 harness

只读 `data/kaipanla/raw` 与 `data/ths/{limit_pool,open_limit_pool}`。
不改交易逻辑，不读 AGENTS.md。

```text
python tools/relay_study/run.py
```

工作目录：仓库根 `D:\Ultra-Board`。

| 文件 | 作用 |
| --- | --- |
| spec.md | 冻结定义、可测 / 不可测、规则、验证门槛 |
| run.py | 复现入口 |
| out/days.csv | 日度 H / 断板 / 爆量 / 题材是否还活 |
| out/leaders.csv | 每日最高板个股 + 成交额比 |
| out/candidates.csv | 每条连板候选与次日结果 |
| out/boards_disagree.csv | 开盘啦 vs 同花顺高度不一致 |
| out/tables.json | 全部格子的原始计数 |
| out/summary.md | 人读摘要 |

主结果是「次日是否还在涨停池 / 是否晋级 / 是否非一字板」，不是打板收益。

## Buyable-path hunt (2026-08-17)

Price-path hunt + new 3-day / theme / open-follow definitions. Does not change `run.py`.

```text
python tools/relay_study/fetch_daily_bars.py
python tools/relay_study/hunt_buyable.py
python tools/relay_study/grid_buyable.py
```

| 文件 | 作用 |
| --- | --- |
| fetch_daily_bars.py | THS last3600 bars for the 1109-code 连板 universe → `out/daily_bars/` |
| hunt_buyable.py | coverage + named events + `out/buyable_hunt.md` |
| grid_buyable.py | combo grid on new price outcomes → `out/buyable_grid.csv` |
| out/buyable_hunt.md | coverage, cells, verdict |
| out/missing_next_bars.csv | candidate rows still without t+1 bar |
| out/theme_persist.csv | theme-day persistence (not a stock fill) |
