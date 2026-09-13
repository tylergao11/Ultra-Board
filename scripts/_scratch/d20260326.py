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


def one(day, code):
    data = load(day)
    hit = next(
        (s for s in data.get("stocks") or [] if str(s.get("code")).zfill(6) == code),
        None,
    )
    if hit:
        is_yz, first, oc, to = yizi(hit)
        return (
            f"在池 {hit.get('boards')} 主题={hit.get('theme')} 属性={tags_of(hit)} "
            f"换手={to} 首封={first} 开板={oc} {'一字' if is_yz else ''}"
        )
    op = THS / f"{day}.json"
    if op.exists():
        od = json.loads(op.read_text(encoding="utf-8-sig"))
        rows = od if isinstance(od, list) else od.get("stocks") or od.get("pool") or []
        exploded = next((s for s in rows if str(s.get("code") or "").zfill(6) == code), None)
        if exploded:
            return (
                f"炸板 换手={exploded.get('turnover_rate')} 涨跌={exploded.get('change_rate')} "
                f"开板={exploded.get('open_count')} 首封={exploded.get('first_limit_time')}"
            )
    return f"不在涨停/炸板池 最高{data.get('max_board')} 涨停{data.get('count')}"


days = [
    "2026-03-18",
    "2026-03-19",
    "2026-03-20",
    "2026-03-23",
    "2026-03-24",
    "2026-03-25",
    "2026-03-26",
]
print("==== 华电辽能 600396 ====")
for d in days:
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        print(d, "NO FILE")
        continue
    print(d, one(d, "600396"))

print()
print("==== 新能泰山 ====")
for d in days:
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        continue
    data = load(d)
    hit = next((s for s in data.get("stocks") or [] if "泰山" in str(s.get("name") or "")), None)
    if hit:
        print(d, hit.get("code"), one(d, str(hit.get("code")).zfill(6)))

data = load("2026-03-26")
print()
print("=" * 8, "2026-03-26", "涨停", data.get("count"), "最高", data.get("max_board"), data.get("board_counts"), "=" * 8)
print("主标签", Counter(str(s.get("theme") or "?") for s in data.get("stocks") or []).most_common(12))
rows = sorted(
    data.get("stocks") or [],
    key=lambda s: (-int(s.get("boards") or 0), ts(s.get("first_limit_ts"))),
)
print("-- 一字 --")
for s in rows:
    is_yz, first, oc, to = yizi(s)
    if is_yz:
        print(
            f"  {s.get('name')} {s.get('boards')}板 主题={s.get('theme')} "
            f"属性={tags_of(s)} 换手={to} 首封={first}"
        )
print("-- 2板+ --")
for s in rows:
    if int(s.get("boards") or 0) < 2:
        continue
    is_yz, first, oc, to = yizi(s)
    print(
        f"  {s.get('name')} {s.get('boards')}板 {'一字' if is_yz else ''} "
        f"主题={s.get('theme')} 属性={tags_of(s)} 换手={to} 首封={first} 开板={oc}"
    )
print("-- 通信/算力/AI --")
for s in rows:
    blob = str(s.get("theme") or "") + " " + tags_of(s)
    if not any(k in blob for k in ("通信", "算力", "人工智能", "AI", "光纤", "光模块")):
        continue
    if int(s.get("boards") or 0) < 1:
        continue
    print(
        f"  {s.get('name')} {s.get('boards')}板 主题={s.get('theme')} "
        f"属性={tags_of(s)} 换手={s.get('turnover_rate')} 首封={ts(s.get('first_limit_ts'))}"
    )
