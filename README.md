# Ultra-Board

Ultra-Board 是本地股票研究、行情证据管理和复盘工具。项目将原始资料、研究规则、研究结论、股票池、行情事件和统计结果收拢到一套可追溯流程中。

当前数据数量用 `python tools/research_cli.py summary` 查询；最新行情日期以 `data/kaipanla/raw/` 实际落盘资料为准。

## 真相源

| 内容 | 正式位置 |
| --- | --- |
| 结构化研究数据 | `data/store/research.sqlite` |
| 静态、动态规则 | `data/store/rules/` |
| 每批研究流程 | `AGENTS.md` |
| 原始行情与证据 | `data/` |
| 当前展示表 | 根目录两张 JSON，由研究库生成 |
| 当前导出批次 | `data/store/exports/current.json` |
| 跨电脑数据库快照 | GitHub Release `research-store-current` |

仓库为公开仓库。设备标识、采集运行状态、令牌、Cookie 和本机缓存均排除在版本控制外。

## 新电脑启用

Windows 电脑安装 Git 和 Python 3 后执行：

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

日常研究按用户指定数量或清单，准备材料后只填写题材与公告判断；补涨、压制、竞争清单和总表自动生成。纠正题材使用 `theme-set --record-key "记录键" --theme "题材"`，相关结果随保存自动更新。默认静态研究，交易研究由买卖表任务负责。新增数据走增量入库；已有资料与草稿直接复用。具体命令见使用说明。

## 目录

```text
data/                   原始下载、研究证据和正式数据
data/store/exports/     当前展示与统计批次
data/store/rules/       正式规则源
docs/                   执行计划、使用说明和多电脑说明
tools/research/         数据库、迁移、查询、统计与恢复实现
tools/research_cli.py   统一命令入口
tools/start_work.ps1    本地开始检查；-Sync 用于跨电脑拉取
tools/finish_work.ps1   本地结束检查；-Sync 用于提交和远端发布
```

## 文档

- [统一研究系统使用说明](docs/研究系统使用说明.md)
- [GitHub 与多电脑使用](docs/GitHub与多电脑使用.md)
- [研究系统执行计划](docs/研究系统执行计划.md)
- [最终验收记录](data/store/migrations/final_acceptance.md)

## GitHub 备份策略

- Git 仓库保存代码、规则、原始资料、研究表、统计、报告和变更历史。
- GitHub Release 保存经过完整性核验的当前 SQLite 数据库及校验清单。
- 本机每日恢复副本保留最近三份，由维护命令轮换；这些副本与正式库内容重复，因此不进入 Git。
- 发布脚本替换滚动 Release 中的数据库资产，避免每日产生一份新的大文件历史。
