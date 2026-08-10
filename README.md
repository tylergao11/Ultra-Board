# Ultra-Board

当前仓库由两层组成：数据层提供可追溯、可核验的盘面事实；研究层围绕资金流向、主线、总核心、日内演变和历史类比形成复盘判断。事实接口不自动生成核心、评分或买点，研究结论也不反向改写行情真相源。

研究思维以 [`AGENTS.md`](AGENTS.md) 为主文档，单日冻结判断保存在 `data/answer/`，完成次日验证的逐案例真相进入 `data/cases/records/`；[`docs/学习训练.md`](docs/学习训练.md) 只保留供人阅读的学习经验汇总。

## 唯一真相合同

- 个股具体题材分类只认开盘啦：`data/kaipanla/raw/YYYY-MM-DD/zt_pool.json` 与 `sector_ladder.json`。
- `stocks[].theme` 是开盘啦主分类；`stocks[].raw[12]` / 读取接口的 `stocks[].themes` 是开盘啦全部具体分类。
- 同花顺故事文件支持两代来源：历史文件保留人工核对的“最强风口”长图；新增交易日自动读取官方历史复盘页的主流看点与盘面脉络，并读取涨停池 `reason_type` 原文作为逐股市场故事。
- 复盘页、标题背景和逐股 `reason_type` 都描述同花顺的市场传播，不覆盖开盘啦分类，也不直接升级为公司、政策或产业事实。
- 股价、流通市值、总市值、换手率、封单、板数、首封、终封、炸板次数、板型与真一字只认 `data/ths/limit_pool/YYYY-MM-DD.json`。
- 同花顺 `reason_type` 原样保存为个股故事，禁止拆分或参与题材归因。
- 上述三层只提供事实；任何核心、节点、梯队角色和买点判断都必须在后续重新建立。

## 数据入口

```powershell
# 更新官方收盘复盘已经公开的最新交易日，并完成全量发布与 API 验证
npm run data:update

# 精确更新指定交易日
npm run data:update -- --date 2026-08-07
```

该入口按顺序处理开盘啦、同花顺涨停池、同花顺日级/逐股故事、完整性门禁、全量 release 原子切换和本地 API 验证。省略日期时读取同花顺官方复盘页的最新有效交易日；显式日期不回退。详细合同见 [每日数据更新契约](docs/每日数据更新契约.md)。

以下命令用于分层诊断或修复：

```powershell
# 数据覆盖、故事缺口与研究记录状态
python tools/data_foundation.py --start 2025-10-09 --end 2026-08-07

# 开盘啦个股分类、题材梯队、情绪与表达原始快照
python -m ultraboard.kaipanla.backfill --start 2026-08-07 --end 2026-08-07

# 同花顺涨停池客观事实
python -m ultraboard.ths.limit_pool 2026-08-07

# 同花顺官方复盘叙事与逐股故事
python -m ultraboard.ths.fupan_stories 2026-08-07
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

## 单交易日 Agent 事实接口

站点不可访问时，直接通过本地统一入口调用全部 `/api/v1` 端点，不需要浏览器或公网：

```powershell
npm run api -- "/api/v1"
npm run api -- "/api/v1/day?date=2026-07-20"
npm run api -- "/api/v1/stocks?date=2026-07-20&code=001258"
```

该命令复用 `site/worker/agent-api.ts` 的正式路由与 `site/public/agent-data/v1` 数据，
统一返回 `ultra_board_local_api` 固定外壳，不复制合同、不联网、不建立第二真相源。

默认一次只读取一个交易日，展示当日题材故事，并返回全部首板和高板。每只股票的概览只保留代码、
名称、板数、板型、主/候选题材和首封时间：

```powershell
python tools/market_day.py 2026-07-24
```

题材、精确板数和板数范围只用于缩小当日集合：

```powershell
python tools/market_day.py 2026-07-24 --theme 智能电网 --board 1
python tools/market_day.py 2026-07-24 --theme AI应用 --theme 机器人 --theme-match all --min-board 2
```

价格、市值、换手、封单、终封、开板次数、连板日期和个股故事不进入默认概览，
由站点 `/api/v1/stocks` 使用 `date` 加可重复的 `code/name` 批量取得。批量详情
任何一只股票或故事缺失都会整体失败，不存在 partial stories 或 `story=null`。

所有输出都标注 `information_cutoff`，不生成爆发、打断、对手、接力、核心、
评分或买点判断。

面向其他 Agent 的站点接口位于 `site/`。接口代码、结构化指南、OpenAPI 和
新闻地址白名单可独立于最终数据开发；最终数据未导出时，`/api/v1/health`
明确返回 `data.status=pending_export`，不会用旧快照或假数据冒充可用。
详细使用方式见 [单交易日事实接口契约](docs/单交易日事实接口契约.md)和
[数据基建](docs/数据基建.md)。

## 目录角色

| 路径 | 角色 |
|---|---|
| `data/kaipanla/raw/` | 开盘啦具体分类与原始市场快照 |
| `ultraboard/kaipanla/` | 开盘啦采集与唯一读取接口 |
| `data/ths/strong_wind_images/` | 历史同花顺官方长图证据（v1） |
| `data/ths/stories/` | 同花顺日级市场叙事与逐股故事（v1/v2） |
| `data/ths/limit_pool/` | 同花顺涨停池客观事实 |
| `ultraboard/ths/` | 同花顺故事与涨停池读取/采集 |
| `AGENTS.md` | 跨交易日复用的资金研究思维与角色定义 |
| `data/answer/` | 按目标日信息截点冻结的单日研究报告 |
| `data/cases/records/` | 一案例一文件的结构化版本真相源 |
| `data/cases/manifest.json` | 案例状态、时间、攻守、结果与检索边界 |
| `docs/学习训练.md` | 从已确认案例提炼的人工阅读汇总 |
| `docs/历史案例契约.md` | 案例时间边界、字段、修订与 RAG 切片合同 |
| `data/knowledge/summaries.jsonl` | 从方法中提炼的原子摘要及修订历史 |
| `.blind-test-quarantine/` | 后验研究隔离区；未经授权禁止读取 |

完整合同见 [数据基建](docs/数据基建.md)。

## 外挂知识库

知识按职责分层：完整通用思维写入 `AGENTS.md`，带日期、环境、时序和后续结果的版本化真相案例写入
`data/cases/records/`，适合单点召回的方法摘要按“一条总结一个切片”保存在
`data/knowledge/summaries.jsonl`。原始行情仍由数据源层负责；任何向量索引都只是
可重建派生物，不是第二真相源。详细边界见 [外挂知识库说明](data/knowledge/README.md)。

```powershell
python tools/knowledge_base.py validate
python tools/knowledge_base.py list --tag 一字板 --tag 换手
python tools/knowledge_base.py export-chunks --output artifacts/knowledge/summaries.jsonl

python tools/case_library.py validate
python tools/case_library.py list --model defense --research-cutoff 2026-08-10T15:00:00+08:00
python tools/case_library.py export-chunks --research-cutoff 2026-08-10T15:00:00+08:00 --output artifacts/knowledge/cases.jsonl
```

默认检索只返回 `accepted`；待验证假设与已被替代的旧版本不会混入当前判断。案例导出的 `retrieval_text` 只包含 T 日条件和冻结路径，验证日结果只进入返回正文与结果元数据，不参与相似度输入。

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

结果揭晓与纠错记录与盲测日志物理隔离；竞价历史缺口也不会用收盘数据反推。研究思维见 [`AGENTS.md`](AGENTS.md)，案例落盘与调用边界见 [历史案例契约](docs/历史案例契约.md)。
