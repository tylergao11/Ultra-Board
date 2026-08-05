轻量上阵，不要搞繁重的交付工程，除非我要求
默认不拉子agent；用户明确要求赛马、并行研究或多agent协作时允许
禁止写测试工程
禁止硬编码
真相源统一
接口清晰

## 节点日盲测边界

- 节点日盲测只能使用日期 T 及以前的 `data/kaipanla/raw/` 原始证据，以及明确标注 `information_cutoff=T` 的派生快照。
- `.blind-test-quarantine/` 是后验研究与人工标签隔离区；除非用户明确结束盲测并授权事后研究，否则禁止列出、搜索、打开、引用或让程序读取其中内容。
- `python -m ultraboard.kaipanla.ladder_evidence node DATE` 是节点收盘安全入口；不得用普通研究文档、人工标签或后续路径替代该入口。
