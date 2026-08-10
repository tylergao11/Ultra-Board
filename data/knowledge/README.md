# 外挂知识库

这里保存逐日研究中提炼出的**原子方法摘要**。它不是第二套行情数据，也不替代完整方法文档和历史案例正文。

## 知识职责与真相源

- [`../../AGENTS.md`](../../AGENTS.md) 是跨交易日研究思维、角色定义和推演逻辑的主文档。
- [`../cases/records`](../cases/records) 是已经完成后验验证的逐案例版本真相；[`../../docs/学习训练.md`](../../docs/学习训练.md) 只承担人工阅读汇总，字段与时间边界见 [`../../docs/历史案例契约.md`](../../docs/历史案例契约.md)。
- `summaries.jsonl` 是从 `AGENTS.md` 投影出的原子方法摘要及其修订账本，一行是一个可独立检索的摘要切片；它不承担历史日内真相记录，也不是独立于 `AGENTS.md` 的第二套方法规则。两者发生语义冲突时，以 `AGENTS.md` 的完整上下文为准，并通过 `supersedes` 修订摘要。
- 原始行情、题材分类、封板过程仍由本地 Agent API 和各自数据源负责；方法与案例均引用事实，不反向改写交易数据。
- 原子方法摘要的向量库、embedding 与搜索缓存都只能由 `summaries.jsonl` 重建，不能反向覆盖摘要真相。
- 只保存对话中已经公开的结论与边界，不保存隐藏思维链。

## 状态

- `accepted`：用户已经确认，可以进入默认检索上下文。
- `hypothesis`：等待后续案例验证，只有显式要求时才取回。
- `superseded`：已经被新总结纠正；保留修订历史，但禁止进入默认上下文。

纠错时保留旧行并把它的状态改为 `superseded`，再新增一条更高 `revision`
的记录，通过 `supersedes` 指向旧记录；旧总结正文不删除。

## 每条切片

每条记录分别保存：

- 一句话总结 `summary`；
- 适用条件 `conditions`；
- 应观察的信号 `signals`；
- 反例与误用边界 `anti_signals`；
- 案例或决策记录引用 `evidence_refs`；
- 修订关系 `supersedes`；
- 用于检索的 `tags`。
- `recorded_at` 与 `temporal_scope`：区分有形成时间证据的方法和只适用于当前方法研究的旧总结。

## 使用

```powershell
# 检查结构、修订顺序和引用关系
python tools/knowledge_base.py validate

# 默认只输出 accepted 总结
python tools/knowledge_base.py list

# 按标签取回候选切片；标签之间为 OR，结果不代表交易评分
python tools/knowledge_base.py list --tag 一字板 --tag 换手

# 严格同时态检索：时间未知或晚于截点的方法不会返回
python tools/knowledge_base.py list --available-at 2026-08-10T18:00:21+08:00

# 导出一行一个切片的 RAG 输入；向量索引以后从这里构建
python tools/knowledge_base.py export-chunks --output artifacts/knowledge/summaries.jsonl
```

方法摘要使用 v2 时间边界：旧总结显式标记为 `current_method_only`，严格同时态查询会排除形成时间未知的记录。历史案例由 `tools/case_library.py` 独立校验并按 `outcome_cutoff` 过滤，避免把验证日结果注入更早的研究上下文。当前尚未安装 embedding；后续只需要对两个工具导出的派生 chunks 建立索引，不改变任一真相源。
