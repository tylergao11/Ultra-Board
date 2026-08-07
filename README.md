# Ultra-Board

当前仓库只建立可追溯的数据源，不包含节点识别、进攻/防守模型、评分或买点结论。

## 唯一真相合同

- 个股具体题材分类只认开盘啦：`data/kaipanla/raw/YYYY-MM-DD/zt_pool.json` 与 `sector_ladder.json`。
- `stocks[].theme` 是开盘啦主分类；`stocks[].raw[12]` / 读取接口的 `stocks[].themes` 是开盘啦全部具体分类。
- 同花顺“最强风口”只提供当日概括故事：人工核对标题，取冒号后的半句，落在 `data/ths/stories/YYYY-MM-DD.json`；不建立 OCR 链路。
- 同花顺标题前半句只是宽泛背景，不得覆盖开盘啦分类；同花顺个股事件文字也不得成为第二套题材。
- 板数、首封、终封、炸板次数、板型与真一字只认 `data/ths/limit_pool/YYYY-MM-DD.json`。
- 上述三层只提供事实；任何核心、节点、梯队角色和买点判断都必须在后续重新建立。

## 数据入口

```powershell
# 开盘啦个股分类、题材梯队、情绪与表达原始快照
python -m ultraboard.kaipanla.backfill --start 2026-08-07 --end 2026-08-07

# 同花顺涨停池客观事实
python -m ultraboard.ths.limit_pool 2026-08-07
```

读取单日开盘啦分类：

```powershell
python -c "from ultraboard.kaipanla import load_day; print(load_day('2026-08-06')['stocks'][0]['themes'])"
```

提取单日动态归因事实：

```powershell
python tools/extract_attribution_evidence.py 2026-08-06 --min-members 2 --groups-only
```

该入口保留开盘啦主 `theme` 与全部归属题材候选，叠加首封、终封、炸板、板型及上午/下午同属性封板序列。它不修改原始分类，也不自动输出主动性、抗压性或带动性结论。

## 目录角色

| 路径 | 角色 |
|---|---|
| `data/kaipanla/raw/` | 开盘啦具体分类与原始市场快照 |
| `ultraboard/kaipanla/` | 开盘啦采集与唯一读取接口 |
| `data/ths/strong_wind_images/` | 同花顺官方长图原始证据 |
| `data/ths/stories/` | 同花顺标题后半句故事 |
| `data/ths/limit_pool/` | 同花顺涨停池客观事实 |
| `ultraboard/ths/` | 同花顺故事与涨停池读取/采集 |
| `.blind-test-quarantine/` | 后验研究隔离区；未经授权禁止读取 |

完整合同见 [数据基建](docs/数据基建.md)。
