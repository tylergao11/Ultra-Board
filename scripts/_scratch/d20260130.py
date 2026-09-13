# -*- coding: utf-8 -*-
import json
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CN = timezone(timedelta(hours=8))
ROOT = Path(r"C:\Ai\Ultra-Board\data\kaipanla\raw")
THS = Path(r"C:\Ai\Ultra-Board\data\ths\open_limit_pool")


def ts(v):
    if not v:
        return ""
    return datetime.fromtimestamp(int(v), CN).strftime("%H:%M")


def load(day):
    return json.loads((ROOT / day / "zt_pool.json").read_text(encoding="utf-8"))


def tags_of(s):
    raw = s.get("raw") or []
    return str(s.get("theme_tags_text") or (raw[12] if len(raw) > 12 else "") or "")


def oc_of(s):
    oc = s.get("open_count")
    raw = s.get("raw") or []
    if oc is None and len(raw) > 16:
        oc = raw[16]
    return oc


def yizi(s):
    first = ts(s.get("first_limit_ts"))
    oc = oc_of(s)
    to = float(s.get("turnover_rate") or 99)
    return first.startswith("09:25") and to <= 6.5 and oc in (0, None, 0), first, oc, to


def show(s, extra=""):
    is_yz, first, oc, to = yizi(s)
    print(
        f"  {s.get('name')} {s.get('boards')}板 {s.get('boards_desc') or ''} "
        f"{'一字' if is_yz else ''} 主题={s.get('theme')} 属性={tags_of(s)} "
        f"换手={to} 首封={first} 开板={oc} "
        f"开={s.get('open')} 高={s.get('high')} 低={s.get('low')} 开幅={s.get('open_pct')}{extra}"
    )


for d in ("2026-01-29", "2026-01-30"):
    data = load(d)
    stocks = data.get("stocks") or []
    print("=" * 8, d, "涨停", data.get("count"), "最高", data.get("max_board"), data.get("board_counts"), "=" * 8)
    print("主标签", Counter(str(s.get("theme") or "?") for s in stocks).most_common(12))
    print("-- 2板+ --")
    for s in sorted(stocks, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        if int(s.get("boards") or 0) < 2:
            continue
        show(s)
    print("-- 一字 --")
    for s in sorted(stocks, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        is_yz, first, oc, to = yizi(s)
        if is_yz:
            show(s)
    keys = ("万丰", "白银", "有色", "湖南黄金", "黄金")
    print("-- 关键词 --")
    for s in stocks:
        blob = f"{s.get('name')} {s.get('theme')} {tags_of(s)}"
        if any(k in blob for k in keys):
            show(s)

print()
print("==== 1.30 炸板里的高位/白银/万丰 ====")
op = THS / "2026-01-30.json"
if op.exists():
    od = json.loads(op.read_text(encoding="utf-8-sig"))
    rows = od if isinstance(od, list) else od.get("stocks") or od.get("pool") or []
    rows = sorted(rows, key=lambda s: -int(s.get("boards") or s.get("limit_times") or 0))
    for s in rows[:25]:
        print(
            f"  {s.get('name')} boards={s.get('boards') or s.get('limit_times')} "
            f"涨跌={s.get('change_rate')} 换手={s.get('turnover_rate')} "
            f"开板={s.get('open_count')} 首封={s.get('first_limit_time')} "
            f"主题={s.get('theme') or s.get('reason')}"
        )
    print("-- 炸板命中 --")
    for s in rows:
        name = str(s.get("name") or "")
        if any(k in name for k in ("万丰", "白银", "黄金", "有色")):
            print(s)
else:
    print("no ths 1.30")
