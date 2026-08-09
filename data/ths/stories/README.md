# 同花顺当日故事

这里保存同花顺对收盘市场的日级叙事与逐股市场故事。它们解释供应商怎样描述当日资金传播，不生成个股题材、公司事实、节点或交易判断。

## v2 自动来源

新增交易日由下列入口生成：

```powershell
python -m ultraboard.ths.fupan_stories YYYY-MM-DD
```

日级叙事来自同花顺官方历史复盘页：`block_1890` 为主流看点，`block_1891` 为盘面脉络。逐股故事来自同花顺涨停池显式请求的 `reason_type` 原文。正式文件将两层分开：

```json
{
  "schema_version": 2,
  "date": "2026-08-07",
  "source": "tonghuashun_fupan_and_limit_up_reasons",
  "source_url": "https://stock.10jqka.com.cn/fupan/20260807.shtml",
  "source_components": {},
  "market_story": {
    "focus": "医药、PCB、金属",
    "headline": "盘面主流看点：医药、PCB、金属",
    "narrative": "盘面脉络原文"
  },
  "stock_stories": [
    {
      "stock_position": 1,
      "code": "601208",
      "name": "东材科技",
      "story": "高速电子树脂+AI算力+中报预增",
      "story_source": "tonghuashun_limit_up_reason_type",
      "mapping_status": "matched_same_day_stock"
    }
  ]
}
```

采集器校验请求日期与页面最后一个有效 `Global.date`、两个来源区块、分页与总数、名码唯一性、非空故事以及 KPL/THS/逐股故事三方股票集合。页面 URL、抓取时间和响应摘要随文件保存。

`reason_type` 保持整串原文，不按 `+` 拆分，也不进入 `theme/themes`、题材索引或题材筛选。复盘页没有可靠的精确发布时间，因此这里的文字只证明收盘复盘归因，不能证明某条事件在 15:00 前已经公开。

## v1 历史兼容

既有交易日继续读取人工核对后的同花顺“最强风口”长图文件：

```json
{
  "date": "2026-08-06",
  "source": "tonghuashun_strong_wind_headlines",
  "source_image": "data/ths/strong_wind_images/2026-08/20260806.png",
  "stories": [
    {
      "source_position": 1,
      "story": "市场并购重组持续活跃；龙头十连板",
      "context": "并购重组",
      "headline": "并购重组：市场并购重组持续活跃；龙头十连板",
      "stocks": []
    }
  ]
}
```

同一天只有一个 canonical 故事文件。已经人工核对的 v1 文件优先保留；自动入口只创建缺失日或刷新同一 v2 来源。人工写入入口仍为：

```powershell
python tools/write_story_day.py YYYY-MM-DD --payload payload.json
```

正式发布要求当日全部股票都有非空逐股故事，完整入口与门禁见 [`docs/每日数据更新契约.md`](../../../docs/每日数据更新契约.md)。
