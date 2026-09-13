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
CODE = "600488"


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


def med_blob(s):
    return str(s.get("theme") or "") + " " + tags_of(s)


def is_med(s):
    b = med_blob(s)
    return any(k in b for k in ("医药", "创新药", "原料药", "疫苗", "中药", "生物"))


days = [
    "2026-03-26",
    "2026-03-27",
    "2026-03-30",
    "2026-03-31",
    "2026-04-01",
    "2026-04-02",
    "2026-04-03",
]

print("==== 津药 600488 ====")
for d in days:
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        print(d, "NO FILE")
        continue
    data = load(d)
    hit = next((s for s in data.get("stocks") or [] if str(s.get("code")).zfill(6) == CODE), None)
    if hit:
        is_yz, first, oc, to = yizi(hit)
        print(
            f"{d} 在池 {hit.get('boards')} {hit.get('boards_desc') or ''} "
            f"主题={hit.get('theme')} 属性={tags_of(hit)} 换手={to} "
            f"首封={first} 开板={oc} {'一字' if is_yz else ''} "
            f"开={hit.get('open')} 高={hit.get('high')} 低={hit.get('low')} "
            f"昨收={hit.get('prev_close')} 开幅={hit.get('open_pct')} "
            f"全场最高{data.get('max_board')} 涨停{data.get('count')}"
        )
        continue
    exploded = None
    op = THS / f"{d}.json"
    if op.exists():
        od = json.loads(op.read_text(encoding="utf-8-sig"))
        rows = od if isinstance(od, list) else od.get("stocks") or od.get("pool") or []
        exploded = next((s for s in rows if str(s.get("code") or "").zfill(6) == CODE), None)
    if exploded:
        print(
            f"{d} 炸板 换手={exploded.get('turnover_rate')} 涨跌={exploded.get('change_rate')} "
            f"开板={exploded.get('open_count')} 首封={exploded.get('first_limit_time')}"
        )
    else:
        print(f"{d} 不在 最高{data.get('max_board')} 涨停{data.get('count')}")

for d in days:
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        continue
    data = load(d)
    stocks = data.get("stocks") or []
    print()
    print("=" * 8, d, "涨停", data.get("count"), "最高", data.get("max_board"), data.get("board_counts"), "=" * 8)
    print("主标签", Counter(str(s.get("theme") or "?") for s in stocks).most_common(12))
    med_theme = [s for s in stocks if str(s.get("theme") or "") in ("医药", "创新药", "原料药", "中药", "生物制品")]
    med_tag = [s for s in stocks if is_med(s)]
    print(f"医药主标签 {len(med_theme)}  主题或标签含医药等 {len(med_tag)}")
    print("-- 医药(标签口径) --")
    for s in sorted(med_tag, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        is_yz, first, oc, to = yizi(s)
        print(
            f"  {s.get('name')} {s.get('boards')}板 {s.get('boards_desc') or ''} "
            f"{'一字' if is_yz else ''} 主题={s.get('theme')} 属性={tags_of(s)} "
            f"换手={to} 首封={first} 开板={oc}"
        )
    print("-- 2板+ 全场 --")
    for s in sorted(stocks, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        if int(s.get("boards") or 0) < 2:
            continue
        is_yz, first, oc, to = yizi(s)
        print(
            f"  {s.get('name')} {s.get('boards')}板 {s.get('boards_desc') or ''} "
            f"{'一字' if is_yz else ''} 主题={s.get('theme')} 属性={tags_of(s)} "
            f"换手={to} 首封={first} 开板={oc}"
        )
    print("-- 一字 --")
    for s in sorted(stocks, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        is_yz, first, oc, to = yizi(s)
        if not is_yz:
            continue
        print(
            f"  {s.get('name')} {s.get('boards')}板 主题={s.get('theme')} "
            f"属性={tags_of(s)} 换手={to} 首封={first}"
        )
