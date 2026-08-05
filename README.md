# Ultra-Board

连板复盘辅助：开盘啦历史涨停池 → 开盘价补全 → 涨停梯队逐日变化材料 → 人工主升判断证据包。

## 主链路（四入口）

在仓库根目录执行：

```bash
# 1) 回灌开盘啦涨停池等到 data/kaipanla/raw/YYYY-MM-DD/
python -m ultraboard.kaipanla.backfill

# 2) 补 ≥2 板开盘价 / 开盘%（挂进同日 ohlc.json 与 zt_pool）
python -m ultraboard.kaipanla.ohlc
# 可选单日：python -m ultraboard.kaipanla.ohlc --day 2026-08-03

# 3) 生成梯队逐日变化材料
python -m ultraboard.review.ladder_daily

# 4) 只取证，不自动选梯队或股票
python -m ultraboard.kaipanla.ladder_evidence node 2025-12-12
python -m ultraboard.kaipanla.ladder_evidence pk 2025-12-12:2
```

依赖：

```bash
pip install -r requirements.txt
```

## 目录角色

| 路径 | 角色 |
|---|---|
| `ultraboard/kaipanla/` | **采集 / 补全**：接口客户端、回灌、日 K 开盘价 |
| `ultraboard/review/` | **复盘派生**：读 raw，写梯队日材料 |
| `ultraboard/limits.py` | 涨跌幅 / 一字等**校验**工具（非主采集） |
| `data/kaipanla/raw/YYYY-MM-DD/` | **主源日目录**（只增不乱改语义） |
| `data/kaipanla/ladder_daily/` | **派生日录**（可随时重生成） |
| `data/kaipanla/ohlc_cache/` | 日 K 缓存（可删可重建，勿当源） |
| `docs/` | 方案与决策记录 |

## 主升研究最小资产

- 客观数据与人工标签共同组成真相库，但事前证据接口禁止读取人工标签。
- `docs/主升梯队资金迁移与逐日个股PK经验.md` 是唯一判断经验源。
- 正式脚本只取证或生成派生材料，不自动宣判梯队、资金流向和买卖状态。
- README 与命令参数构成薄接口契约；临时赛马、排名和收益报告不长期保存。

数据细节见 `data/kaipanla/README.md`。

## 增量扩展约定

1. **读**：新特征优先读 `data/kaipanla/raw/YYYY-MM-DD/`（`zt_pool.json` / `ohlc.json` / `sector_ladder.json`…）。
2. **写派生**：新复盘产物写到 `data/kaipanla/` 下独立派生目录（仿 `ladder_daily/`），**不要**覆盖 raw 日文件语义。
3. **代码挂载**：
   - 新数据源 / 补全 → `ultraboard/kaipanla/`
   - 新复盘视图 / 材料 → `ultraboard/review/`
   - 价位规则校验 → `ultraboard/limits.py` 或同级小模块
4. **正式入口唯一**：正式能力放在 `ultraboard/`，临时探针用完即删。

后续可加（当前未做门禁）：爆量规则、修全量 `_MISMATCH`、全历史 OHLC 覆盖、竞价层。

## 包导入

```bash
python -c "import ultraboard; import ultraboard.kaipanla; import ultraboard.review; print('ok')"
```
