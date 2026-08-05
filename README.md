# Ultra-Board

连板复盘辅助：开盘啦历史涨停池 → 开盘价补全 → 涨停梯队逐日变化材料 → 人工主升判断证据包。

## 主链路

在仓库根目录执行：

```bash
# 1) 回灌开盘啦涨停池等到 data/kaipanla/raw/YYYY-MM-DD/
python -m ultraboard.kaipanla.backfill

# 2) 补 ≥2 板开盘价 / 开盘%（挂进同日 ohlc.json 与 zt_pool）
python -m ultraboard.kaipanla.ohlc
# 可选单日：python -m ultraboard.kaipanla.ohlc --day 2026-08-03

# 3) 生成梯队逐日变化材料
python -m ultraboard.review.ladder_daily

# 4) 节点日证据（不自动选层）
python -m ultraboard.kaipanla.ladder_evidence node 2025-12-12
python -m ultraboard.kaipanla.ladder_evidence pk 2025-12-12:2

# 5) 第一阶段统一选层（严格不读 T+1）
python -m ultraboard.review.ladder_selector select 2025-12-12

# 显式事后回测；普通 select 不读取标签
python -m ultraboard.review.ladder_selector backtest --labels .blind-test-quarantine/labels/stage1_locked.json

# 6) 第二阶段节点日竞价预期分 E（含冻结层内预期 PK，仍严格不读 T+1）
python -m ultraboard.review.candidate_initial_score 2025-12-24

# 7) 显式后验：T+1 实际竞价 A、超预期差 Δ 与收盘晋级校准
python -m ultraboard.review.auction_score review 2025-12-24 --fetch-missing
python -m ultraboard.review.auction_score backtest --labels .blind-test-quarantine/labels/stage1_locked.json --fetch-missing
```

依赖：

```bash
pip install -r requirements.txt
```

## 目录角色

| 路径 | 角色 |
|---|---|
| `ultraboard/kaipanla/` | **采集 / 补全**：接口客户端、回灌、日 K 开盘价 |
| `ultraboard/review/` | **复盘派生与决策**：节点日统一选层、竞价预期 E，以及显式后验 A/Δ 校准 |
| `ultraboard/limits.py` | 涨跌幅 / 一字等**校验**工具（非主采集） |
| `data/kaipanla/raw/YYYY-MM-DD/` | **主源日目录**（只增不乱改语义） |
| `data/kaipanla/ladder_daily/` | **派生日录**（可随时重生成） |
| `data/kaipanla/ohlc_cache/` | 日 K 缓存（可删可重建，勿当源） |
| `docs/` | 节点日可见的方案与判断经验 |
| `.blind-test-quarantine/` | 后验研究、人工标签与完整后续路径；盲测禁止访问 |

## 主升研究最小资产

- 客观数据与人工标签共同组成真相库，但事前证据接口禁止读取人工标签。
- `docs/主升梯队资金迁移与逐日个股PK经验.md` 是唯一判断经验源。
- 第一阶段选层由 `ladder_selector` 按唯一规则自动完成；第二阶段生成节点日竞价预期 E，并对同梯队自然票做预期／实际 PK，再由显式后验入口计算实际 A 与 Δ。单票梯队不伪造 PK，最终选票、放弃与买卖状态仍不自动宣判。
- README 与命令参数构成薄接口契约；临时赛马、排名和收益报告不长期保存。
- 节点日盲测只走 `ladder_evidence node DATE`；隔离区仅在用户明确授权事后研究时开放。

数据细节见 `data/kaipanla/README.md`。

## 增量扩展约定

1. **读**：新特征优先读 `data/kaipanla/raw/YYYY-MM-DD/`（`zt_pool.json` / `ohlc.json` / `sector_ladder.json`…）。
2. **写派生**：新复盘产物写到 `data/kaipanla/` 下独立派生目录（仿 `ladder_daily/`），**不要**覆盖 raw 日文件语义。
3. **代码挂载**：
   - 新数据源 / 补全 → `ultraboard/kaipanla/`
   - 新复盘视图 / 材料 → `ultraboard/review/`
   - 价位规则校验 → `ultraboard/limits.py` 或同级小模块
4. **正式入口唯一**：正式能力放在 `ultraboard/`，临时探针用完即删。

后续可加（当前未做门禁）：爆量规则、修全量 `_MISMATCH`、全历史 OHLC 覆盖、09:25 实时竞价采集器。

## 包导入

```bash
python -c "import ultraboard; import ultraboard.kaipanla; import ultraboard.review; print('ok')"
```
