# 结构化历史案例库

这里保存 Ultra-Board 历史案例的逐版本结构化真相。每个 `records/*.json` 文件是一条独立案例版本；同一案例通过稳定的 `case_id` 归组，通过 `record_id=<case_id>@<revision>` 区分版本。

## 真相源边界

- `records/*.json`：案例条件、冻结决策、后续判卷、时间边界与修订关系的唯一真相源。
- 当前案例库为空。新案例只从结构化冻结记录与正式行情判卷生成，不迁移旧学习材料。
- RAG chunks、embedding、关键词索引和向量索引：全部是可删除、可重建派生物。

## 时间与结果隔离

`condition_axes`、`market_structure` 和 `decision` 只保存节点日 `decision_cutoff` 以前可见的事实与冻结路径。`outcome` 单独保存验证日及后续反馈。`retrieval_tags` 禁止混入成功、无交易、吃面等结果标签。

默认案例召回必须满足：

1. `case_status=closed`；
2. `retrieval_status=accepted`；
3. `outcome_cutoff` 严格早于当前研究的 `information_cutoff`；
4. 向量相似度输入只使用工具生成的 `retrieval_text`，不使用 `outcome`。

`retrieval_text` 采用字段白名单生成，只读取 `retrieval_tags`、四个条件轴、节点结构和节点日冻结路径。旧案例标题、案例问题、相似性复述及完整结果即使含有后验措辞，也不会进入向量输入。

## 使用

```powershell
# 校验全部案例、修订链和时间边界
python tools/case_library.py validate

# 按结构字段查看当前可召回案例
python tools/case_library.py list --model defense --research-cutoff 2026-08-10T15:00:00+08:00

# 导出供后续 embedding 使用的派生切片
python tools/case_library.py export-chunks --research-cutoff 2026-08-10T15:00:00+08:00 --output artifacts/knowledge/cases.jsonl
```

`export-chunks` 同时输出：

- `retrieval_text`：按字段白名单生成，只包含 T 日条件、结构与冻结决策，用于相似度计算；
- `text`：包含条件、决策和历史结果，供召回后阅读；
- `metadata`：时间、状态、攻守模型、高度和修订信息，供硬过滤。

新增案例从 `case_template.json` 复制字段结构，但必须使用新的稳定 `case_id`。纠错时不覆盖旧文件：提高 `revision`、生成新 `record_id`，通过 `supersedes` 指向旧版本，并把旧版本标记为 `superseded`。
