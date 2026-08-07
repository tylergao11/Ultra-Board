# 外挂知识库

这里保存我们在逐日训练中**逐条确认的总结**。它不是第二套行情数据，也不是模型权重。

## 单一真相

- `summaries.jsonl` 是总结的唯一真相源，一行就是一个完整 RAG 切片。
- 原始行情、题材分类、封板过程仍由各自数据源负责；总结只引用事实，不复制和改写事实。
- 向量库、embedding 与搜索缓存都只能由 `summaries.jsonl` 重建，不能反向覆盖总结。
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

当前先使用结构化标签和 Codex 推理选择切片。等总结规模真正超过人工可控范围，再为同一出口增加向量索引；不提前引入另一套模型。
