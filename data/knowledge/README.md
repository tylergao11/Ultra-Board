# 外挂知识库

这里保存逐日研究中提炼出的**原子方法摘要**。它不是第二套行情数据，也不替代完整方法文档和历史案例正文。

## 知识职责与真相源

- [`../../AGENTS.md`](../../AGENTS.md) 是跨交易日研究思维、角色定义和推演逻辑的主文档。
- [`../../docs/学习训练.md`](../../docs/学习训练.md) 是已经完成后验验证的历史案例正文；字段与时间边界见 [`../../docs/历史案例契约.md`](../../docs/历史案例契约.md)。
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

## 使用

```powershell
# 检查结构、修订顺序和引用关系
python tools/knowledge_base.py validate

# 默认只输出 accepted 总结
python tools/knowledge_base.py list

# 按标签取回候选切片；标签之间为 OR，结果不代表交易评分
python tools/knowledge_base.py list --tag 一字板 --tag 换手

# 导出一行一个切片的 RAG 输入；向量索引以后从这里构建
python tools/knowledge_base.py export-chunks --output artifacts/knowledge/summaries.jsonl
```

当前脚本只校验和导出 `summaries.jsonl` 中的原子摘要。现有摘要没有制品时间字段，只服务当前方法检索，不作为严格同时态回放中“当时已经掌握该方法”的证据。历史案例 Markdown 的按时间过滤与 RAG 导出尚未接入该脚本；在实现案例索引前，研究按 `outcome_cutoff` 定向读取案例，不把整份案例库注入早于其结果截点的研究上下文。等知识规模真正超过人工可控范围，再为同一出口增加向量索引。
