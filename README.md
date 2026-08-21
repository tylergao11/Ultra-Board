# Ultra-Board

Ultra-Board 用开盘啦历史收盘快照提供可追溯的涨停池、题材分类、梯队和市场情绪事实。数据层只整理事实，不自动判断龙头、补涨、切换、核心或买点。

## 数据原则

- 正式市场事实只读开盘啦；
- 个股历史题材归属只认开盘啦当日主分类；
- 主分类缺失时保留 `null`，股票仍进入完整涨停池；
- 连板高度只认开盘啦 `DailyLimitPerformance` 个股真实连板字段；
- 反包只作标记，不抬高连续板数；
- ST与北交所不进入目标打板市场，排除记录必须闭合；
- 来源没有提供的最终封板、炸板次数、板型、市值、封单和故事保持不可得；
- 会回填后来概念的附加标签只保留原始值，不进入历史筛选与回测；
- 历史同花顺目录保留为旧研究证据，但不再进入正式读取链。

详细字段合同见 [数据基建](docs/数据基建.md)。

## 安装

```powershell
npm install
python -m pip install requests
```

## 数据更新

```powershell
# 自动刷新并选择最近完整交易日
npm run data:update

# 更新指定交易日
npm run data:update -- --date 2026-08-21

# 自动续传一个历史闭区间
npm run data:update -- --start 2024-07-22 --end 2025-10-09
```

区间回灌会跳过已有完整日和开盘啦确认的非交易日，网络失败后重跑同一命令即可继续。完整流程见 [每日数据更新契约](docs/每日数据更新契约.md)。

## 单日事实查询

```powershell
# 默认返回当日全部正式涨停股票
python tools/market_day.py 2026-08-21

# 按开盘啦题材和板数筛选
python tools/market_day.py 2026-08-21 --theme 机器人 --min-board 2
python tools/market_day.py 2026-08-21 --board 3 --compact
```

输出包含：

- 市场涨跌与涨跌停摘要；
- 首板、高板、最高板和板数分布；
- 开盘啦题材梯队；
- 个股代码、名称、板数、当日主分类和首次封板时间；
- 明确的 `information_cutoff` 与来源合同。

## 跨日事实查询

```powershell
# 单日紧凑视图
python tools/market_memory.py brief 2025-11-06

# 个股在开盘啦涨停池中的连续出现路径
python tools/market_memory.py path 000993 2025-11-06 --start 2025-11-04
```

跨日工具只读取截止日及以前的开盘啦日快照，不用后续结果重写历史。

## 目录角色

| 路径 | 角色 |
|---|---|
| `data/kaipanla/raw/` | 唯一正式日快照 |
| `data/kaipanla/non_trading_days.json` | 开盘啦确认的非交易日或历史未入库日 |
| `ultraboard/kaipanla/` | 开盘啦采集与读取合同 |
| `ultraboard/day_facts.py` | 单日事实组装 |
| `tools/market_day.py` | 单日命令行查询 |
| `tools/market_memory.py` | 跨日路径与梯队查询 |
| `data/ths/`、`ultraboard/ths/` | 旧同花顺证据与采集代码，不进入正式链 |
| 旧故事工具与 `tools/relay_study/` | 历史研究复现区，可能读取旧同花顺文件，不属于正式入口 |
| `data/research/` | 明确标注来源与时间边界的研究材料 |

市场分析思维见 [AGENTS.md](AGENTS.md)。
