# Ultra-Board

当前仓库只建立可追溯的数据源，不包含节点识别、进攻/防守模型、评分或买点结论。

## 唯一真相合同

- 个股具体题材分类只认开盘啦：`data/kaipanla/raw/YYYY-MM-DD/zt_pool.json` 与 `sector_ladder.json`。
- `stocks[].theme` 是开盘啦主分类；`stocks[].raw[12]` / 读取接口的 `stocks[].themes` 是开盘啦全部具体分类。
- 同花顺“最强风口”只提供当日概括故事：人工核对标题，取冒号后的半句，落在 `data/ths/stories/YYYY-MM-DD.json`；不建立 OCR 链路。
- 同花顺标题前半句只是宽泛背景，不得覆盖开盘啦分类；同花顺个股事件文字也不得成为第二套题材。
- 股价、流通市值、总市值、换手率、封单、板数、首封、终封、炸板次数、板型与真一字只认 `data/ths/limit_pool/YYYY-MM-DD.json`。
- 同花顺 `reason_type` 禁止参与题材归因。
- 上述三层只提供事实；任何核心、节点、梯队角色和买点判断都必须在后续重新建立。

## 数据入口

```powershell
# 数据覆盖、故事缺口与研究记录状态
python tools/data_foundation.py --start 2025-10-09 --end 2025-12-31

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

该入口保留开盘啦主 `theme` 与全部归属题材候选，叠加同花顺身位、股价、流通市值、封单、首封、终封、炸板、板型及上午/下午同属性封板序列。它不修改原始分类，也不自动输出主动性、抗压性或带动性结论。

生成节点日轻量决策视图：

```powershell
python tools/extract_attribution_evidence.py 2026-08-06 --decision-view
```

该视图只读取日期 T 与上一交易日，标注 `information_cutoff=T`。默认保留全部涨停，板数只是事实；`--candidate-min-boards` 只能缩小展示范围，不能成为交易排除条件。视图展示上一梯队去向、T 日一字/换手状态、候选属性的首封与最终回封双时序；真一字只作为方向与身位指引，并映射同身位、共享属性的非一字票，不自动生成核心、评分或买点。

## 五日动态事实包

默认读取截止日及之前五个本地数据日。每日 `stocks` 只展开全市场二板及
以上，但二板以上只是明细展示阈值，不是动态链起点：凡窗口内进入二板及
以上的股票，`stock_paths` 和 `board_sequence_facts` 都会自动回带其可用的
首板事实，完整记录 `1_to_2`：

```powershell
python tools/market_replay.py 2026-07-24
```

市场逐日观察链与个股来源连板链分开保存。若个股中间没有当日记录，逐日路径
保持 `null`；只有同花顺 `consecutive_limit_up_dates` 明确确认连板日期时，
`board_sequence_facts` 才跨过空档连接板数。空档不会被自动标记为失败、停牌，
也不会伪造开盘啦属性的删除和重新增加。

传入题材后，精确匹配开盘啦 `theme/themes`，返回该题材五日内的全部
涨停股票，包括首板：

```powershell
python tools/market_replay.py 2026-07-24 --theme 智能电网
```

尚未进入二板的首板不会因此塞入默认明细。只有明确需要全市场首板时才展开
全部涨停：

```powershell
python tools/market_replay.py 2026-07-24 --include-all-first-boards
```

沿相同参数继续到下一个本地数据日：

```powershell
python tools/market_replay.py 2026-07-24 --theme 智能电网 --next
```

输出保留同花顺 `stories` 的当日原始记录，但故事不覆盖开盘啦个股属性。
默认包同时提供紧凑题材索引。尚未进入二板的首板明细仍留在本地来源中，
按 `--theme` 下钻读取；已发生的一进二路径则自动返回，不需要额外参数。
所有输出都标注 `information_cutoff`、逐日来源覆盖和源间股票差异，不生成
爆发、打断、对手、接力、核心、评分或买点判断。

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

## 外挂知识库

逐日训练中已经确认的认识按“一条总结一个切片”保存在
`data/knowledge/summaries.jsonl`。原始行情仍由数据源层负责；任何向量索引都只是
可重建派生物，不是第二真相源。

```powershell
python tools/knowledge_base.py validate
python tools/knowledge_base.py list --tag 一字板 --tag 换手
python tools/knowledge_base.py export-chunks --output artifacts/knowledge/summaries.jsonl
```

默认检索只返回 `accepted`；待验证假设与已被替代的旧总结不会混入当前判断。

## 跨日研究与蒸馏

```powershell
# 单日紧凑视图
python tools/market_memory.py brief 2025-11-06

# 个股连续涨停路径
python tools/market_memory.py path 000993 2025-11-06 --start 2025-11-04

# 一字核心开门、失败及同身位竞争证据
python tools/market_memory.py competition 2025-11-06

# 人工指定节点的资金记忆池
python tools/market_memory.py pool 2025-11-06 2025-11-28

# 默认只验证揭晓前记录
python tools/training_records.py validate
```

结果揭晓与纠错记录与盲测日志物理隔离；竞价历史缺口也不会用收盘数据反推。完整使用方式见 [研究与蒸馏工作流](docs/研究与蒸馏工作流.md)。
