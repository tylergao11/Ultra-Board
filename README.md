# Ultra-Board

根据首板、二板当时的消息和启动节点细分归类，围绕核心次日是否被迫一字，讨论一字首开回封。开盘啦提供来源事实，软件标签不替代炒作属性判断。

交易口径只读 [AGENTS.md](AGENTS.md)，接口说明只读 [数据基建](docs/数据基建.md)，继续位置见 [节点接力复盘接续](docs/节点接力复盘接续.md)。

## 复盘查询

```powershell
# 查询个股当前属性对应的板块编号；不把当前属性说明回填历史
python -m ultraboard.kaipanla.query concepts 000533 --name 数据中心

# 同一个板块的两日涨停数量及完整名单
python -m ultraboard.kaipanla.query breadth --plate 801460 --before 2024-12-30 --day 2024-12-31

# 当日涨停名单、板数、首封和供应商一字标记
python -m ultraboard.kaipanla.query pool 2024-12-31
python -m ultraboard.kaipanla.query pool 2025-01-02 --code 000533
```

查询优先使用本地缓存；缺少板块成员或天梯时一次采集后复用。股票和板块编号均为命令参数，示例不构成选股规则。

## 日数据维护

```powershell
npm run data:update -- --date YYYY-MM-DD
python tools/data_foundation.py --start YYYY-MM-DD --end YYYY-MM-DD
python tools/market_day.py YYYY-MM-DD
```

日维护合同见 [每日数据更新契约](docs/每日数据更新契约.md)。事实数据存放在各供应商日目录；复盘查询不要求重新下载整个月，不自动生成交易结论。
