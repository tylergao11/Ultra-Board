# 开盘啦主源与派生

## 结构

```
data/kaipanla/
  device_id.txt              # 开盘啦 DeviceID，固定复用
  backfill_state.json
  announcement_overrides.json # 原始主属性漏标时的公告事件覆盖（不含梯队答案）
  ohlc_cache/                # 日 K 按代码缓存（gitignore）
  raw/YYYY-MM-DD/            # 主源日目录
    zt_pool.json             # 涨停池（≥2 可含 open/open_pct）
    ohlc.json                # 当日 ≥2 板 OHLC（可选，ohlc 步骤生成）
    sector_ladder.json        # 涨停原因发酵榜原序 + 板块梯队 + 反包
    sentiment.json
    expression.json
    _DONE | _MISMATCH
  ladder_daily/              # 复盘派生：严格截至同日的梯队逐日变化
```

## 主命令（在仓库根执行）

```bash
python -m ultraboard.kaipanla.backfill   # 回灌 raw
python -m ultraboard.kaipanla.ohlc       # 补 ≥2 板开盘价（首板不写）
python -m ultraboard.review.ladder_daily # 生成 ladder_daily/
```

## 口径摘要

- 主属性 = 开盘啦 `theme`（**禁止用接口概念堆 raw[12]/concepts**）
- 神剑排名 = `sector_ladder.json` 原始发酵榜前二；禁止按数量重排或让第三名递补
- 公告起源只认并购重组/实控人变更/股权转让；举牌、业绩、摘帽、订单和再融资均为自然属性
- 公告起源在连续连板段中保持；漏标只允许由 `announcement_overrides.json` 修正
- 梯队材料只列 **≥2 板**；首板只作发酵计数
- **开盘%** 仅 ≥2 板；来自日 K 挂载，非开盘啦 raw 自带
- 跟随链：安全日文件只保存截至该日已经发生的路径；完整后续路径进入隐藏隔离区

扩展约定见仓库根 `README.md`。
