# GitHub 与多电脑使用

## 采用的方案

项目使用“Git 仓库 + 滚动数据库 Release”两层备份：

- Git 仓库保存原始资料、代码、规则、生成表、统计和核验报告。
- GitHub Release `research-store-current` 保存当前正式 SQLite 数据库、SHA-256 和机器可读清单。
- 本机 `data/store/recovery/` 保存短期滚动恢复副本，由 `maintain` 自动保留最近三份。

正式数据库约 403 MB。GitHub 普通 Git 的单文件上限为 100 MiB；Git LFS 每次修改都会计入一个完整的新版本。滚动 Release 让下载地址保持稳定，同时控制大文件版本数量。

## 家里电脑首次启用

```powershell
git clone https://github.com/tylergao11/Ultra-Board.git
Set-Location Ultra-Board
powershell -ExecutionPolicy Bypass -File tools/setup_home.ps1
```

脚本执行顺序：

1. 读取 Release 中的 `database_release_manifest.json`。
2. 比较本地数据库 SHA-256。
3. 下载缺失的数据库到项目内登记的临时目录。
4. 校验大小和 SHA-256。
5. 原子移动到 `data/store/research.sqlite`。
6. 运行 `summary`，显示数据库批次、当前规则来源和主要表计数。

本地已有另一版数据库时，脚本会保留现状并提示。确定以 GitHub 快照覆盖时运行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/setup_home.ps1 -Force
```

被替换的数据库会移动到 `data/store/local-backups/`，便于回退。

## 按需同步与换电脑

日常查询和修改直接落本机数据库。用户明确要求同步、远端备份或换电脑时才联系 GitHub。另一台电脑接收工作：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_work.ps1 -Sync
```

当前电脑交出工作：

```powershell
powershell -ExecutionPolicy Bypass -File tools/finish_work.ps1 -Sync -Message "本次工作摘要"
```

加 `-Sync` 后，`start_work.ps1` 检查工作区、快进拉取 GitHub、安装当前数据库并保留最多两份本机旧库；`finish_work.ps1` 检查本机结果，提交、推送并更新滚动数据库 Release。省略 `-Sync` 时两个入口均只操作本机。底层脚本保留给 agent 排障和单项操作。

## 单独发布数据库

```powershell
powershell -ExecutionPolicy Bypass -File tools/publish_database_release.ps1
```

发布前通过 SQLite 备份接口生成独立一致快照，包含 WAL 中已提交的数据；校验值、表计数和上传文件均取该快照。Release 固定包含：

- `research.sqlite`
- `research.sqlite.sha256`
- `database_release_manifest.json`

发布脚本需要 GitHub CLI。已通过 Git 登录的电脑会复用 Git Credential Manager 中的 GitHub 凭据；也支持已设置的 `GH_TOKEN`。

## 冲突处理

两台电脑同时研究时，先在一台完成研究写入、导出和数据库发布，再在另一台执行 `git pull` 与 `setup_home.ps1 -Force`。开始覆盖前，脚本会把另一台的现有数据库移入本机备份目录。

原始资料和 JSON 冲突使用 Git 处理。SQLite 数据库通过当前 Release 整体切换，避免二进制合并。
