# 开盘啦主源与派生

## 结构

```
data/kaipanla/
  device_id.txt              # 开盘啦 DeviceID，固定复用
  backfill_state.json
  announcement_taxonomy.json # 公告型 theme 唯一分类表
  ohlc_cache/                # 日 K 按代码缓存（gitignore）
  raw/YYYY-MM-DD/            # 主源日目录
    zt_pool.json             # 涨停池（≥2 可含 open/open_pct）
    ohlc.json                # 当日 ≥2 板 OHLC（梯队算法就绪门禁）
    sector_ladder.json        # 涨停原因题材家数 + 接口源字段/源序 + 板块梯队 + 反包
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

- 个股 `theme` = `DailyLimitPerformance` 梯队列表字段 `raw[5]`；代码为 `raw[19]`（**禁止读取个股详情属性或接口概念堆 raw[12]/concepts**）
- `zt_pool.json.source_reconciliation` 对 `DailyLimitPerformance` 每条源记录逐条记账；北交所记录明确放入排除账。`HisZhangFuDetail.SJZT` 市场范围更宽，只作跨接口参考，不能再用它制造假缺口
- `_DONE` 只表示四份开盘啦主源已通过同源对账；梯队算法还会逐日强制检查 `ohlc.json` 与每只 ≥2 板的 `open/high/low/prev_close`，任一缺失即整体拒绝运行
- 成功响应若缺少合法 `info[0]`、中心 `theme/raw[5]` 或 `sector_code/raw[19]`，采集直接失败，不写完成标记
- 进攻模型排名 = `sector_ladder.json` 题材家数 + `zt_pool.json` 同 theme 成交额，按同期客户端画面确认的“家数、成交额”排序后取前二；最高连板不参与该榜排序
- 创业板与主板均按各自真实连板数进入梯队；不得按代码前缀整板过滤
- 公告型 theme 只认 `announcement_taxonomy.json`；涵盖 ST摘帽、举牌、定期报告、订单、再融资、重组等，不包含仍戴帽的 ST／*ST 股票
- 公告／自然身份只看最高板当天的梯队 theme；断板时看断板前一交易日，不继承更早身份
- 前一日最高自然梯队断板才触发节点；若该票断板前一日 theme 为公告，其断板不触发自然节点
- 真一字只认同一价格口径下开盘价=最高价=最低价；不得用 09:25 首封或开盘涨停代替
- 梯队材料只列 **≥2 板**；首板 `theme` 可作市场宽度计数，但不改变任何股票的当日身份
- **开盘%** 仅 ≥2 板；来自日 K 挂载，非开盘啦 raw 自带
- 跟随链：安全日文件只保存截至该日已经发生的路径；完整后续路径进入隐藏隔离区

扩展约定见仓库根 `README.md`。
