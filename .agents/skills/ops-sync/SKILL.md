---
name: ops-sync
description: >-
  跨电脑 GitHub 数据库同步交接、开盘啦每日历史行情回补与候选入库、出生补涨题材/压制专项审计修复、数据库维护与代码自检工作流。当用户要求拉取/推送最新数据库、更新每日涨停池数据、排查缺项或执行系统维护时激活（也可通过 /ops-sync 调用）。
---

# 跨机同步、数据采集入库与系统维护工作流

> **同步边界与双机铁律（家 ↔ 公司来回更新必守）**：
> - **同机连续作业**：全部在本地完成，不联网碰 GitHub。
> - **换电脑开工唯一入口**：一律执行 `start_work.ps1 -Sync`（自动 `git pull --ff-only` + 下载校验 Release 正式库，并默认保留 1 份换库前旧库于 `data/store/local-backups/`）；**严禁只做 `git pull` 不拉数据库**。
> - **换电脑收工唯一出口**：一律执行 `finish_work.ps1 -Sync -Message "本次摘要"`（自动刷新导出、远端防撞检查、`git push` 并更新滚动 Release）；**严禁只推 Git 不发库，或两边同时改再硬推**。
> - **程序硬闸门保护**：`status` 输出 `sync_health`；所有写入命令在检测到本机库落后于 Git `current.json` 或 `dynamic_rules.json` 哈希不一致（且存在动态记录）时会自动报错停手，绝不静默清空动态库。
> - **用户说“拉最新数据 / 更新到最新”时**：先查 `status` 的 `sync_health`（若已换机或告警，先做跨机同步），再跑开盘啦每日行情回补与候选入库。

## 一、跨电脑同步与数据库交接

项目采用 **“Git 仓库（代码/规则/原始资料/导出表）+ GitHub 滚动 Release `research-store-current`（SQLite 正式库快照）”** 双层机制：

1. **接收端（开工拉取最新代码与正式库）**：
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File tools/start_work.ps1 -Sync
   ```
   - 若 Git 已是最新、仅需强制拉取并校验替换 Release 数据库快照（内置 `curl.exe` 自动断点续传、SHA-256 严格校验，默认保留 1 份换库前旧库备份）：
     ```powershell
     powershell -NoProfile -ExecutionPolicy Bypass -File tools/setup_home.ps1 -Force
     ```
2. **交出端（收工核验、远端防撞检查、提交推送并更新滚动数据库 Release）**：
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File tools/finish_work.ps1 -Sync -Message "本次工作摘要"
   ```
   - 仅在本地执行结束检查与导出刷新（不联网）：省略 `-Sync`。
   - 单独发布数据库快照：`powershell -NoProfile -ExecutionPolicy Bypass -File tools/publish_database_release.ps1`。

## 二、开盘啦每日行情回补与新候选登记

1. **按交易日补齐涨停分组、题材消息与板块梯队并入库**：
   ```powershell
   python -B tools/research_cli.py daily-backfill --from-date YYYY-MM-DD --to-date YYYY-MM-DD --report data/research/<目录>/acquisition.json
   ```
   - 只读审计原始分组、展示池与数据库齐备度：加 `--audit-only`；确认旧展示池漏行追加：加 `--reconcile-missing`。
2. **手工新增文件入库、同步二板及以上严格一字首开候选并触发自动推导**：
   ```powershell
   python -B tools/research_cli.py ingest --path <资料文件或目录>
   python -B tools/research_cli.py candidate-sync --from-date YYYY-MM-DD --to-date YYYY-MM-DD
   python -B tools/research_cli.py derive
   ```
3. **停牌事实核验入库**：核实公告覆盖日期后写入 `data/market_status/*.json`（`kind: "reviewed_suspensions"`），再运行 `ingest --path <文件>`。
4. **属性接口空标签板块反查**：退市或空属性票使用 `research.attribute_membership.recover(store, codes, catalogue_path, quote_date)` 全目录核查后入库（标记 `historical_membership_verified=false`，仅在允许倒推的范围内使用）。

## 三、专项修复、日常维护与改码自检

1. **出生当日补涨题材补填 / 只读审计**：
   ```powershell
   python -B tools/research_cli.py birth-themes --from-date YYYY-MM-DD --to-date YYYY-MM-DD --preview
   python -B tools/research_cli.py birth-themes --from-date YYYY-MM-DD --to-date YYYY-MM-DD --audit
   ```
2. **一字压制日期专项核验修复**：
   ```powershell
   python -B tools/research_cli.py suppression-repair --from-date YYYY-MM-DD --to-date YYYY-MM-DD --preview
   ```
3. **状态诊断、缺项排查与日常维护**：
   ```powershell
   python -B tools/research_cli.py status
   python -B tools/research_cli.py summary
   python -B tools/research_cli.py issues
   python -B tools/research_cli.py impact --object <代码或证据路径>
   python -B tools/research_cli.py temp-clean
   python -B tools/research_cli.py maintain
   python -B tools/research_cli.py verify
   ```
4. **备份与恢复演练**（仅用户明确要求备份时执行）：
   ```powershell
   python -B tools/research_cli.py backup --output data/store/recovery/current
   python -B tools/research_cli.py restore-drill --backup <备份文件.sqlite> --report <报告.json>
   ```
5. **修改 `tools/` 代码后的强制验收红线**（`findings` 必须为 `0` 且单测全过）：
   ```powershell
   python -B tools/research_cli.py selfcheck
   python -B -m unittest discover -s tools/research -p "test_*.py" -t tools
   ```
