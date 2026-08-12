# Ultra-Board 本地 Agent API

该目录只提供正式发布组件的只读查询层。行情真相仍由仓库根目录下的开盘啦、同花顺数据源负责；`public/agent-data/v1` 是可重建的发布产物。

```powershell
npm run api -- "/api/v1/health"
npm run api -- "/api/v1/calendar"
npm run api -- "/api/v1/day?date=2026-08-07"
npm run api -- "/api/v1/stocks?date=2026-08-07&code=002552"
```

重新构建正式发布组件：

```powershell
python tools/export_agent_site_data.py --ready-only
```

CLI 输出固定的 `ultra_board_local_api` 外壳；真实 HTTP 状态、响应正文与错误码位于 `response` 字段。`ULTRA_BOARD_PUBLIC_ROOT` 可把同一路由指向待发布 staging，用于每日更新的原子验证。
