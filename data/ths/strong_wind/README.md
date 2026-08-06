# 同花顺最强风口逐日数据

本目录是正式且唯一的逐日分类真相源，内容人工抄录自同花顺官方“涨停聚焦 → 最强风口”历史长图。

- 一天一个 `YYYY-MM-DD.json`。
- `groups` 严格保持图片从上到下的顺序，`rank` 从 1 开始。
- 分类必填字段是 `groups[].rank`、`groups[].title` 与每只股票的 `code`、`name`。
- `groups[].title` 明确为“公告”或“公告题材”时，该组股票直接按公告题材处理，禁止把“公告”解释成自然题材。
- 当且仅当原分组是“其他”“其他概念”或同义的未分类兜底项时，人工读取该股票行的事件介绍，直接把股票改归到明确的有效题材，不在最终结构化数据中继续保留“其他”。原始页面证据由 `source_image` 保存。
- “其他概念”股票必须先由人工确认当天真实封板主驱：若主驱是该股自身的并购、拟收购、控制权变更、业绩预增等独立事件，统一归为“公告题材”；若实际随行业／概念板块联动，则归入对应自然题材。不得只因事件文字出现公告词或概念词就直接分类。
- 脚本只负责列出待审核股票及事件原文，不得用正则、关键词或规则表生成题材建议。人工决定统一记录在 `../strong_wind_manual_reviews.json`。
- `summary`、`board`、`limit_time`、`reason` 是可选核对字段，能够可靠提取时保留原文，不能可靠提取时可省略，不影响分类数据有效性。
- 必填字段看不清时写 `null`，并在顶层 `issues` 中说明，禁止猜测。
- 除上述“其他/未分类”例外外，正常明确大类不得根据行内事件介绍再次改类。若人工改归题材当天没有原生同名分组，新增分组放在原有明确分组之后，不改变同花顺原有前二顺序。

图片原件位于相邻目录 `../strong_wind_images/`。

## 批量生成

通用脚本：`tools/build_ths_strong_wind.py`。

安装依赖：

```powershell
python -m pip install rapidocr-onnxruntime Pillow numpy
```

处理一个月：

```powershell
python tools/build_ths_strong_wind.py --month 2025-11 --workers 1 --overwrite
```

处理完整研究区间：

```powershell
python tools/build_ths_strong_wind.py --start 2025-10-01 --end 2026-07-31 --workers 1 --overwrite
```

脚本将官方图片作为分组证据，只用当天 `../limit_pool/YYYY-MM-DD.json` 校正 OCR 股票代码和名称。“其他/未分类”没有人工决定时写入每日 `issues`，不得自动建议、静默猜测或直接归类。
