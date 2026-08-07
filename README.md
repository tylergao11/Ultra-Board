# Ultra-Board

以同花顺“涨停聚焦 → 最强风口”为唯一题材真相的节点日与连板梯队复盘工具。

## 唯一真相合同

- 个股当天题材、公告身份、风口顺序只读取 `data/ths/strong_wind/YYYY-MM-DD.json`。
- 同花顺已有明确大类时保留原分组；只有“其他/其他概念/未分类”逐股人工判断真实封板驱动后，才改归自然题材或“公告题材”。
- 人工票并入海报已有大类时继承该大类原位次；拆出海报未单列的新题材时不虚构风口排名，但仍参与自然最高层、节点日和防守/无模型选层。
- `data/ths/limit_pool/YYYY-MM-DD.json` 是板数、首封、终封、炸板次数、板型与真一字的唯一客观事实源。
- `boards` 表示当前连续涨停高度；`boards_desc` 原样保留同花顺的 `N天M板` 窗口描述。二者不得混用。
- 日文件存在待审问题、兜底分组、漏归股票或涨停池合同异常时，节点入口直接失败，不猜测、不回退到另一套来源。

## 主链路

在仓库根目录执行：

```powershell
# 1. 从同花顺官方“最强风口”原图生成逐日分类；兜底组必须先人工审核
python tools/build_ths_strong_wind.py --month 2025-11 --workers 1 --overwrite --strict

# 旧日文件只补齐海报原位次与人工归属来源，不重跑股票 OCR
python tools/build_ths_strong_wind.py --all --provenance-only --workers 1 --strict

# 2. 按同花顺真相列出区间内全部节点日和冻结梯队
python -m ultraboard.ths.ladder_selector list 2025-10-01 2025-12-31

# 机器可读输出
python -m ultraboard.ths.ladder_selector list 2025-10-01 2025-12-31 --json

# 生成站点唯一可读的同花顺派生快照
python -m ultraboard.ths.site_export 2025-10-01 2025-12-31 --output site/public/data/ths-nodes.json
```

同花顺涨停池按需补齐或强制回刷：

```powershell
python -m ultraboard.ths.limit_pool 2026-08-06
python -m ultraboard.ths.limit_pool --start 2025-10-01 --end 2026-08-06 --force
```

## 目录角色

| 路径 | 角色 |
|---|---|
| `data/ths/strong_wind_images/` | 同花顺官方“最强风口”原图证据 |
| `data/ths/strong_wind/` | 唯一逐日题材、公告身份与风口顺序真相 |
| `data/ths/strong_wind_manual_reviews.json` | “其他概念”逐股人工驱动审核结论 |
| `data/ths/limit_pool/` | 当前连续板数、封板过程、板型与真一字真相 |
| `ultraboard/ths/` | 同花顺真相校验、节点检测与进攻/防守模型 |
| `site/public/data/ths-nodes.json` | 经正式节点入口校验后生成的只读站点快照 |
| `.blind-test-quarantine/` | 后验研究隔离区；未经用户明确授权禁止访问 |

判断规则见 [同花顺最强风口节点与进攻防守模型](docs/同花顺最强风口节点与进攻防守模型.md)，数据合同见 [数据基建](docs/数据基建.md)。

## 包导入

```powershell
python -c "import ultraboard; import ultraboard.ths; print('ok')"
```
