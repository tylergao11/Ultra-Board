# Ultra-Board

Ultra-Board 是本地股票研究、行情证据管理和复盘工具。项目将原始资料、研究规则、研究结论、股票池、行情事件和统计结果收拢到一套可追溯流程中。

当前数据数量用 `python tools/research_cli.py summary` 查询；最新行情日期以 `data/kaipanla/raw/` 实际落盘资料为准。

## 真相源与分层架构

本项目以**超短盘面思维逻辑**为核心，文档与规则按 Google Antigravity 原生工作流体系分层解耦、互不复制：

| 层级 | 正式位置 | 职责 |
| --- | --- | --- |
| 结构化研究数据 | `data/store/research.sqlite` | 唯一正式结论与行情事实库 |
| 静态、动态规则 | `data/store/rules/` | 唯一机读业务口径（`static_rules.json` / `dynamic_rules.json`） |
| 盘面裁决思维内核 | `docs/研究思路与碰撞笔记.md` | 活体《盘面裁决逻辑说明书》（共生群落、二板定性、防表皮欺骗） |
| 常驻行为红线 | `AGENTS.md` | Agent 角色定位、硬约束与零绕路准则 |
| 渐进式工作流 Skills | `.agents/skills/` | `/static-review`（静态复盘）、`/trade-review`（动态卡位买卖）、`/ops-sync`（同步入库维护） |
| 原始行情与证据 | `data/` | 开盘啦每日涨停池、题材消息、板块梯队与行情快照 |
| 当前展示表 | 根目录两张 JSON（由研究库生成） | 当前导出批次由 `data/store/exports/current.json` 指定 |
| 跨电脑数据库快照 | GitHub Release `research-store-current` | 滚动正式库快照与 SHA-256 清单 |

仓库为公开仓库。设备标识、采集运行状态、令牌、Cookie 和本机缓存均排除在版本控制外。

## 新电脑启用

Windows 电脑安装 Git 和 Python 3 后执行：

日K与开盘啦行情取数使用 Python 标准库；在线获取同花顺封板时间明细时另需 Node.js。

```powershell
git clone https://github.com/tylergao11/Ultra-Board.git
Set-Location Ultra-Board
powershell -ExecutionPolicy Bypass -File tools/setup_home.ps1
```

`setup_home.ps1` 会从 GitHub 当前数据库快照下载 `research.sqlite`，核对 SHA-256，放入正式位置并输出研究库摘要。

启用后可立即查询：

```powershell
python -B tools/research_cli.py summary
python -B tools/research_cli.py stock --code 603366
python -B tools/research_cli.py rules
```

## 日常流程

日常研究直接使用本机数据库。需要检查本地状态时使用：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_work.ps1
```

本地工作检查入口：

```powershell
powershell -ExecutionPolicy Bypass -File tools/finish_work.ps1 -Message "本次工作摘要"
```

这两个入口默认在本地运行。用户要求同步或换电脑时，当前电脑运行 `tools/finish_work.ps1 -Sync -Message "交接工作"`，另一台运行 `tools/start_work.ps1 -Sync`。每批研究、改题材和改口径完成后直接报告结果。

日常研究按用户指定数量或日期范围，通过 `/static-review` 工作流准备材料后，结合盘面思维框架填写唯一主炒与补涨盘面逻辑；补涨命中、一字压制、潜在竞争对手清单和总表自动生成。纠正题材使用 `theme-set --record-key "记录键" --theme "题材"`，相关结果随保存自动级联更新。静态研究（`/static-review`）和交易研究（`/trade-review`）严格隔离，行情与同步维护统一走 `/ops-sync`。

## 目录

```text
.agents/skills/         Antigravity 渐进式场景工作流（/static-review、/trade-review、/ops-sync）
data/                   原始下载、研究证据和正式数据
data/store/exports/     当前展示与统计批次
data/store/rules/       正式规则源
docs/                   盘面裁决逻辑说明书、CLI 参考手册与跨机同步说明
tools/research/         数据库、采集、查询、静态推导与统计实现
tools/research_cli.py   统一命令入口
tools/start_work.ps1    本地开始检查；-Sync 用于跨电脑拉取
tools/finish_work.ps1   本地结束检查；-Sync 用于提交和远端发布
```

## 文档与工作流入口

- [盘面裁决逻辑说明书（核心思维内核）](docs/研究思路与碰撞笔记.md)
- [静态复盘工作流 `/static-review`](.agents/skills/static-review/SKILL.md) | [动态交易工作流 `/trade-review`](.agents/skills/trade-review/SKILL.md) | [同步与运维工作流 `/ops-sync`](.agents/skills/ops-sync/SKILL.md)
- [统一研究系统 CLI 参考说明](docs/研究系统使用说明.md)
- [GitHub 与多电脑使用](docs/GitHub与多电脑使用.md)
- [当前数据核验](data/store/verification/current/verification.json)

## GitHub 备份策略

- Git 仓库保存代码、规则、原始资料、研究表、统计、报告和变更历史。
- GitHub Release 保存经过完整性核验的当前 SQLite 数据库及校验清单。
- 本机日常操作不生成恢复副本；明确要求备份时才执行备份入口。
- 发布脚本替换滚动 Release 中的数据库资产，避免每日产生一份新的大文件历史。
