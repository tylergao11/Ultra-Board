# 开盘啦历史数据

目录：`D:\Ultra-Board\data\kaipanla`

## 结构

```
data/kaipanla/
  device_id.txt            # 固定设备号，勿删勿改
  backfill_state.json      # 回灌进度
  non_trading_days.json    # 已确认假期（无日期目录）
  raw/
    YYYY-MM-DD/            # 仅交易日；假期不建目录
      HisZhangFuDetail.json
      ZhangTingExpression.json
      ladder.json
      _DONE
```

## 回灌

```bash
python -m ultraboard.kaipanla.backfill
```

- 区间：2025-10-01 ~ 今天
- 间隔：1~2 秒随机
- 支持断点续传：已有 `_DONE` 的日期自动跳过
- 失败即停；修好后重新运行即可续拉

## 字段提示

`ladder.json` 里每只股票是位置数组，关键下标：

| 下标 | 含义 |
|---|---|
| 0 | 代码 |
| 1 | 名称 |
| 4 | 首封时间戳 |
| 5 | 主题材 |
| 12 | 概念标签 |
| 15 | 连板高度 |
| 19 | 板块代码 |
| 21 | 涨停价附近价位 |
| 22 | 涨幅 |

`ladder["1"]` 是首板（气氛组），`ladder["2"]` 及以上是连板梯队。
