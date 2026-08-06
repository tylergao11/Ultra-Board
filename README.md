# Ultra-Board

以同花顺“涨停聚焦 → 最强风口”为唯一题材真相的节点日与连板梯队复盘工具。

## 唯一真相合同

- 个股当天题材、公告身份、风口顺序只读取 `data/ths/strong_wind/YYYY-MM-DD.json`。
- 同花顺已有明确大类时保留原分组；只有“其他/其他概念/未分类”逐股人工判断真实封板驱动后，才改归自然题材或“公告题材”。
- `data/kaipanla/raw/` 仅提供板数、OHLC、封板时间等客观事实。其历史 `theme`、`sector_ladder`、概念或公告字段均不是决策输入。
- 日文件存在待审问题、兜底分组、漏归股票或二板以上 OHLC 缺失时，节点入口直接失败，不猜测、不回退到另一套分类。

## 主链路

在仓库根目录执行：

```powershell
# 1. 从同花顺官方“最强风口”原图生成逐日分类；兜底组必须先人工审核
python tools/build_ths_strong_wind.py --month 2025-11 --workers 1 --overwrite --strict

# 2. 按同花顺真相列出区间内全部节点日和冻结梯队
python -m ultraboard.ths.ladder_selector list 2025-10-01 2025-12-31

# 机器可读输出
python -m ultraboard.ths.ladder_selector list 2025-10-01 2025-12-31 --json
```

客观行情缓存按需补齐：

```powershell
python -m ultraboard.kaipanla.backfill
python -m ultraboard.kaipanla.ohlc
python -m ultraboard.kaipanla.ths_limit_pool 2026-08-06
```

这些命令不赋予开盘啦题材任何决策权。

## 目录角色

| 路径 | 角色 |
|---|---|
| `data/ths/strong_wind_images/` | 同花顺官方“最强风口”原图证据 |
| `data/ths/strong_wind/` | 唯一逐日题材、公告身份与风口顺序真相 |
| `data/ths/strong_wind_manual_reviews.json` | “其他概念”逐股人工驱动审核结论 |
| `ultraboard/ths/` | 同花顺真相校验、节点检测与进攻/防守模型 |
| `data/kaipanla/raw/` | 板数、OHLC、封板时间等客观事实缓存；分类字段禁用 |
| `ultraboard/kaipanla/` | 客观事实采集与补全，不参与题材判断 |
| `.blind-test-quarantine/` | 后验研究隔离区；未经用户明确授权禁止访问 |

判断规则见 [同花顺最强风口节点与进攻防守模型](docs/同花顺最强风口节点与进攻防守模型.md)，数据合同见 [数据基建](docs/数据基建.md)。

## 包导入

```powershell
python -c "import ultraboard; import ultraboard.ths; import ultraboard.kaipanla; print('ok')"
```
