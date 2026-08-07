轻量上阵，不要搞繁重的交付工程，除非我要求
默认不拉子agent；用户明确要求赛马、并行研究或多agent协作时允许
禁止写测试工程
禁止硬编码
真相源统一
接口清晰

## 节点日盲测边界

- 节点日盲测的题材、公告身份与风口排名只能使用日期 T 及以前的 `data/ths/strong_wind/`；板数、封板时间、板型与真一字只能使用日期 T 及以前的 `data/ths/limit_pool/`。
- 同花顺是唯一真相源；禁止引入第二套题材、连板或封板过程来源。
- `.blind-test-quarantine/` 是后验研究与人工标签隔离区；除非用户明确结束盲测并授权事后研究，否则禁止列出、搜索、打开、引用或让程序读取其中内容。
- `python -m ultraboard.ths.ladder_selector list START END` 是节点收盘安全入口；输出必须标注 `information_cutoff=T`，不得用人工标签或 T+1 结果倒灌。
