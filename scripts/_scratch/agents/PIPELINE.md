# 两段式流水线：ML 结构分 → 情绪题材子 Agent

```
节点日 T
  │
  ├─ Stage 1  机器训练/打分
  │    train_cont_score_ml.py
  │    → ml_cont_scores.csv / ml_cont_model.json
  │    特征：首封、一字、锚点、发酵字段排名、层内竞争…
  │    不含「真实题材纠偏」（theme 字面不可信）
  │
  ├─ Stage 1.5  打包
  │    pack_for_sentiment_agent.py --day T
  │    → agent_packs/{T}_ml_pack.json
  │
  └─ Stage 2  子 Agent（sentiment_theme_scorer）
       读 pack + raw 日数据
       探查：真实主线、真实发酵排名、层内谁最好
       输出：agent_score 0~100 + 打/不打 + best_only
```

## 分工

| 层 | 负责 | 不负责 |
|----|------|--------|
| ML | 可量化结构先验 | 合富=福建 这类叙事 |
| 子 Agent | 真实情绪/题材/唯一最优 | 改 ML 权重 |

## 命令

```bash
# 训练/更新 ML
python scripts/_scratch/train_cont_score_ml.py

# 打包某节点日
python scripts/_scratch/pack_for_sentiment_agent.py --day 2025-10-30

# 子 Agent：按 agents/sentiment_theme_scorer.md 吃 pack，吐 JSON
```

## 人机标签

`human_labels_v1.json` 写入 pack 的 principles，子 Agent 必须遵守「只打最好的」等。
