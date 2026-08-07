# 同花顺当日故事

这里仅保存人工核对后的同花顺“最强风口”标题。冒号后的概括性故事是主要字段；不建立 OCR 链路，也不保存个股题材分类、风口排名、节点或进攻/防守判断。

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
      "headline": "并购重组：市场并购重组持续活跃；龙头十连板"
    }
  ]
}
```

`story` 是主要字段；`context` 只是标题前半句的宽泛背景，不得用于覆盖开盘啦分类。

如标题下同时录入同花顺图片中可见的个股故事，在对应故事项内增加可选
`stocks` 数组：

```json
{
  "source_position": 1,
  "story": "市场并购重组持续活跃；龙头十连板",
  "context": "并购重组",
  "headline": "并购重组：市场并购重组持续活跃；龙头十连板",
  "stocks": [
    {
      "stock_position": 1,
      "code": "603221",
      "name": "爱丽家居",
      "story": "图片中可见的个股故事原文",
      "mapping_status": "matched_same_day_stock"
    }
  ]
}
```

只有能与同日开盘啦或同花顺涨停池唯一对应时才填写 `code`；否则使用
`code=null`、`mapping_status=unresolved`。个股故事不得生成或覆盖
`theme/themes`，完整五日接口合同见 `docs/五日动态事实包契约.md`。
