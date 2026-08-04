# 开盘啦主源与派生

## 结构

```
data/kaipanla/
  device_id.txt              # 开盘啦 DeviceID，固定复用
  backfill_state.json
  ohlc_cache/                # 日 K 按代码缓存（gitignore）
  raw/YYYY-MM-DD/            # 主源日目录
    zt_pool.json             # 涨停池（≥2 可含 open/open_pct）
    ohlc.json                # 当日 ≥2 板 OHLC（可选，ohlc 步骤生成）
    sector_ladder.json
    sentiment.json
    expression.json
    _DONE | _MISMATCH
  ladder_daily/              # 复盘派生：梯队逐日变化（可重跑覆盖）
```

## 主命令（在仓库根执行）

```bash
python -m ultraboard.kaipanla.backfill   # 回灌 raw
python -m ultraboard.kaipanla.ohlc       # 补 ≥2 板开盘价（首板不写）
python -m ultraboard.review.ladder_daily # 生成 ladder_daily/
```

## 口径摘要

- 主属性 = 开盘啦 `theme`；公告板（举牌/实控人变更/并购重组/股权转让）标 `[公告板]` 并可带成交额
- 梯队材料只列 **≥2 板**；首板只作发酵计数
- **开盘%** 仅 ≥2 板；来自日 K 挂载，非开盘啦 raw 自带
- 跟随链：≥2→断→反包→再连板，按日跟随高标高度

扩展约定见仓库根 `README.md`。
