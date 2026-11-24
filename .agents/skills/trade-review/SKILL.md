---
name: trade-review
description: >-
  一字首开动态交易研究、首开日竞价与卡位PK、上午买点核验、封板率及断板尾盘卖出收益计算工作流。仅在用户明确安排交易研究或动态核验时激活（也可通过 /trade-review 调用）；日常静态复盘严禁调用本流程中的分时与封板接口。
---

# 动态交易研究与首开卡位工作流

> **前置边界**
> - 仅在用户明确安排交易研究时执行；静态结论在此阶段**严格只读**，不触发静态推导。
> - **红线警告**：`data/store/rules/dynamic_rules.json` 改动任意一个字节（含空格/换行），全库所有动态交易记录（含用户已确认记录）都会被判作废并删除！非用户明确改交易口径严禁触碰，改前必须说明该后果。

## 一、开工必读动态口径

```powershell
python -B tools/research_cli.py status; python -B tools/research_cli.py rules --scope all
```

核心判定准绳以 `data/store/rules/dynamic_rules.json` 为唯一依据（纯5板只做先锋：高标池起点及当日断板前最低连续板数均为5板，仅放行未命中任何≥5板高标的先锋，补涨与蹭股一律淘汰 + 静态无一字压制（含高身位与同身位20cm一字） + 动态禁忌主炒黑名单（①医药大桶：医药/医疗器械/脑机接口/生育三胎/养老银发；②并购重组：纯并购重组及夕阳+夕阳；仅作用于主炒，不改静态属性归并） + 09:25主板10cm竞价未被卡位（20cm/30cm不参与次日竞价比较；不设低开禁止门槛；高身位10cm涨停开直接卡死，同身位双10cm涨停开比09:25初始封单金额取最大者） + 中午前实际触发首次上板或上午首开且上午首次回封 + 同轮仅买一次 + 断板日尾盘卖出）。

## 二、常规动态批次流程（完整买卖与卡位研究）

1. **准备动态批次与行情事实**：
   ```powershell
   python -B tools/research_cli.py batch-prepare --scope dynamic --output data/research/<动态批次目录> --from-date YYYY-MM-DD --to-date YYYY-MM-DD
   ```
   - 单独预检/补齐候选及竞争对手日K与分时事件：
     ```powershell
     python -B tools/research_cli.py market-ensure --from-date YYYY-MM-DD --to-date YYYY-MM-DD --days 20
     python -B tools/research_cli.py trade-facts --record-key "代码|日期" --days 20
     ```
   - 精确补取指定股票日期的日行情、分钟分时及同花顺毫秒级封板时间明细（`--details` 需 Node.js）：
     ```powershell
     python -B tools/research_cli.py market-fetch --code <六位代码> --date YYYY-MM-DD --details
     ```
2. **核查与填写 `decisions.json`**：
   - 对照 `brief.json` 中的候选首开行情 `market` 与竞争对手盘口 `competitor_market`，核查竞价（`auction`）、同题材竞争对手卡位对比（`pk_checks` / `pk_result`）、上午实际买点（`buy_point`）及断板日尾盘卖出收益（`outcome`）。
3. **提交与核验**：
   ```powershell
   python -B tools/research_cli.py batch-commit --batch data/research/<动态批次目录>; python -B tools/research_cli.py batch-verify --batch data/research/<动态批次目录>
   ```
   *(程序判断仅作为待确认结果，严禁批量覆盖用户已确认的统一交易清单。)*

## 三、专项核验入口速查

1. **仅核查首开买点与当日封板率（`buy_seal` 五阶段）**：
   在已有动态批次目录上以 `PYTHONPATH=tools` 依次运行 `prepare`、`scan`、`fetch`、`evaluate`、`commit`（只看首开当日加 `--buy-day-only`；仅写回已核清独立启动轮加 `--commit-resolved`；时间区间证据保存在批次 `reviewed-observations.json` 的 `time_window`）：
   ```powershell
   $env:PYTHONPATH="tools"; python -B -m research.buy_seal evaluate --batch data/research/<批次目录> --buy-day-only
   ```
2. **上午买点时段全量核验**：
   ```powershell
   python -B tools/research_cli.py morning-audit --report data/research/afternoon-buy-audit/current.json
   ```
   *(核对无误后加 `--commit` 写回剔除与时点证据。)*
3. **断板日尾盘卖出收益重算**：
   ```powershell
   python -B tools/research_cli.py tail-close --report data/research/trade-review-2025-2026/tail-close.json
   ```
   *(核对无误后加 `--commit` 写回并刷新展示表。)*
4. **增量资料入库后刷新已有动态批次行情引用**：
   ```powershell
   $env:PYTHONPATH="tools"; python -B -m research.buy_seal refresh-facts --batch data/research/<批次目录>
   ```
