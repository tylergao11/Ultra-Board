# 研究与蒸馏记录

这里保存**揭晓前**形成的可审计决策记录。每次记录必须先于结果写入，并显式标注 `information_cutoff`。

## 两层隔离

- `data/training/decisions.jsonl`：盲测安全层，只能写入当时已知事实、候选、排除条件与预期形态。
- `.blind-test-quarantine/distillation/`：后验训练层，保存用户揭晓、纠错、被否定规则和最终接受的学习；任何日常判断工具不得读取。

当前对话中已经揭晓的案例被标为 `post_outcome_training_only`，不能冒充实时预测。记录只保存我们在对话中公开表达的判断依据，不保存或生成隐藏思维链。

## 记录字段

- `record_id` / `sequence`：稳定身份与对话顺序。
- `record_type`：原则、揭晓前选择、结果揭晓、纠错或工作流假设。
- `case_date` / `information_cutoff`：市场日期与信息截止日。
- `user_signal`：用户原话或不改变含义的紧凑摘录。
- `public_reasoning_summary`：当时公开给出的判断依据。
- `decision` / `outcome` / `correction`：选择、结果和纠错，未发生时为 `null`。
- `accepted_learning`：纠错后保留的训练标签。
- `supersedes`：被当前记录替代的旧记录。

## 使用

```powershell
# 默认只验证盲测安全层
python tools/training_records.py validate

# 显式验证后验训练记录；不得在盲测分析中调用
python tools/training_records.py validate --scope post-outcome --allow-post-outcome

# 生成可供后续蒸馏的 messages JSONL
python tools/training_records.py export-sft --scope post-outcome --allow-post-outcome --output artifacts/training/conversation_alignment.jsonl
```

未来新增中文记录时使用 `apply_patch`，文件保持 UTF-8 无 BOM。
