# Ultra-Board 本地数据查询指南

本文件只说明本地数据的查询入口、命令、参数和字段边界。

## 一、首选入口：本地 Agent API

在仓库根目录执行。该命令直接调用 `site/worker/agent-api.ts`，读取 `site/public/agent-data/v1/`，不需要启动服务器、浏览器或访问公网。

### 1. 检查数据状态

```powershell
npm run api -- "/api/v1/health"
```

只有健康响应中的正式数据状态可用时，才继续查询交易日。

### 2. 查询正式交易日

```powershell
npm run api -- "/api/v1/calendar"
```

只能从响应的 `available_dates` 中选择日期，不得把自然日直接当作交易日。

### 3. 查询一个交易日的完整概览

```powershell
npm run api -- "/api/v1/day?date=2026-07-24"
```

默认返回该日全部来源股票，包括全部首板和更高板，并包含日级市场状态、题材索引、板块故事、股票概览和前后可用交易日指针。

每次 `/day` 只返回一个交易日。需要连续多日时，根据 `navigation.previous_available_date` 或 `navigation.next_available_date` 逐日再次请求，不得假定相邻自然日就是交易日。

### 4. 按题材和板数缩小单日集合

```powershell
# 单一题材的首板
npm run api -- "/api/v1/day?date=2026-07-24&theme=智能电网&board=1"

# 任一题材命中，二板及以上
npm run api -- "/api/v1/day?date=2026-07-24&theme=智能电网&theme=机器人&theme_match=any&min_board=2"

# 同时命中两个题材，二板至四板
npm run api -- "/api/v1/day?date=2026-07-24&theme=AI应用&theme=机器人&theme_match=all&min_board=2&max_board=4"

# 精确查询一板、二板和五板
npm run api -- "/api/v1/day?date=2026-07-24&board=1&board=2&board=5"
```

参数规则：

- `theme` 可重复，最多 8 个；
- `theme_match=any` 表示任一题材命中，`all` 表示全部命中；
- `board` 可重复，最多 16 个，多值取并集；
- `min_board`、`max_board` 均包含边界；
- `board` 不能与 `min_board` 或 `max_board` 同时使用；
- 题材条件与板数条件取交集。

### 5. 批量查询个股完整详情

```powershell
# 按代码批量查询
npm run api -- "/api/v1/stocks?date=2026-07-24&code=600123&code=000001"

# 代码和精确名称可以混用
npm run api -- "/api/v1/stocks?date=2026-07-24&code=600123&name=某某股份"
```

`code` 和 `name` 都可以重复传入，单次最多 32 个唯一选择器。名称只支持精确匹配；名称不唯一时改用代码。

批量详情是原子请求：任一股票未找到、名称不唯一、个股故事缺失或故事正文为空，整批请求失败，不会返回部分结果。

个股详情用于取得默认日概览没有展开的价格、市值、换手、封单、首封、终封、开板次数、板型、连板日期和逐股故事。

## 二、机器发现端点

```powershell
npm run api -- "/api/v1"
npm run api -- "/api/v1/meta"
npm run api -- "/api/v1/guide"
npm run api -- "/api/v1/openapi"
npm run api -- "/api/v1/themes?date=2026-07-24"
npm run api -- "/api/v1/stories?date=2026-07-24"
npm run api -- "/api/v1/news/sources"
```

- `/api/v1`：端点总入口；
- `/meta`：参数上限和查询边界；
- `/guide`：数据调用顺序与完整说明；
- `/openapi`：OpenAPI 3.1 合同；
- `/themes`：指定日期的题材索引；
- `/stories`：指定日期的板块故事；
- `/news/sources`：允许访问的新闻与公告来源。

## 三、Python 单日概览快捷入口

只需要快速查看单日股票和题材时，可以使用：

```powershell
python tools/market_day.py 2026-07-24
python tools/market_day.py 2026-07-24 --theme 智能电网 --board 1
python tools/market_day.py 2026-07-24 --theme AI应用 --theme 机器人 --theme-match all --min-board 2
```

该工具仍遵守单交易日事实接口边界。需要完整个股详情时，改用 `/api/v1/stocks`。

## 四、直接读取正式 JSON

优先使用本地 Agent API。只有检查原始结构或排查接口问题时，才直接读取文件。

```powershell
# 正式发布日期和修订信息
Get-Content -Raw -Encoding UTF8 "site/public/agent-data/v1/manifest.json" | ConvertFrom-Json

# 正式单日组件
Get-Content -Raw -Encoding UTF8 "site/public/agent-data/v1/days/2026-07-24.json" | ConvertFrom-Json

# 开盘啦原始涨停池、梯队和情绪
Get-Content -Raw -Encoding UTF8 "data/kaipanla/raw/2026-07-24/zt_pool.json" | ConvertFrom-Json
Get-Content -Raw -Encoding UTF8 "data/kaipanla/raw/2026-07-24/sector_ladder.json" | ConvertFrom-Json
Get-Content -Raw -Encoding UTF8 "data/kaipanla/raw/2026-07-24/sentiment.json" | ConvertFrom-Json

# 同花顺涨停事实与故事
Get-Content -Raw -Encoding UTF8 "data/ths/limit_pool/2026-07-24.json" | ConvertFrom-Json
Get-Content -Raw -Encoding UTF8 "data/ths/stories/2026-07-24.json" | ConvertFrom-Json
```

正式可用日期以 `manifest.json` 的 `available_dates` 为准。原始目录中存在文件，不代表该日期已经满足正式发布合同。

## 五、字段来源与缺失值

- 个股主属性和候选属性来自开盘啦；
- 板数、价格、市值、换手、封单、首终封、开板次数、板型和真一字来自同花顺涨停池；
- 板块故事和逐股故事来自同花顺故事数据；
- `context` 是来源上下文，不等于个股题材；
- `null` 表示来源未提供或无法确认，不能改写成 `0`、`false` 或“没有”；
- 个股故事缺失时不得用题材、新闻或默认文字补造；
- 所有日期判断以响应中的 `information_cutoff` 和 `trade_date` 为准。

## 六、查询错误处理

- `DATE_NOT_FOUND`：日期未正式发布，回到 `/calendar` 重新选择；
- `STOCK_NOT_FOUND`：至少一个代码或名称未命中；
- `AMBIGUOUS_STOCK_NAME`：名称不唯一，改用股票代码；
- `BOARD_FILTER_CONFLICT`：同时使用了 `board` 和板数范围；
- `STOCK_STORY_INCOMPLETE`：个股故事不完整，不能把本次响应当作完整事实；
- `DATA_CONTRACT_ERROR`：正式组件不符合 Schema，应停止使用该响应。

## 七、详细合同

- `docs/单交易日事实接口契约.md`：端点、参数、响应字段和错误码；
- `docs/每日数据更新契约.md`：数据更新与发布流程；
- `docs/数据基建.md`：数据源、目录职责和完整性边界；
- `site/README.md`：本地 API 调用示例。
