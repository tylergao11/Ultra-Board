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


def sent(day):
    p = ROOT / day / "sentiment.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("info") or {}


def tags_of(s):
    raw = s.get("raw") or []
    return str(s.get("theme_tags_text") or (raw[12] if len(raw) > 12 else "") or "")


days = [
    "2026-02-24",
    "2026-02-25",
    "2026-02-26",
    "2026-02-27",
    "2026-03-02",
    "2026-03-03",
]

print("==== 豫能 001896 ====")
for d in days:
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        print(d, "NO FILE")
        continue
    data = load(d)
    hit = next(
        (s for s in data.get("stocks") or [] if str(s.get("code")).zfill(6) == "001896"),
        None,
    )
    if hit:
        raw = hit.get("raw") or []
        oc = hit.get("open_count")
        if oc is None and len(raw) > 16:
            oc = raw[16]
        print(
            f"{d} 在池 {hit.get('boards')} {hit.get('boards_desc') or ''} "
            f"主题={hit.get('theme')} 属性={tags_of(hit)} 换手={hit.get('turnover_rate')} "
            f"首封={ts(hit.get('first_limit_ts'))} 开板={oc} 全场最高{data.get('max_board')}"
        )
        continue
    exploded = None
    op = THS / f"{d}.json"
    if op.exists():
        od = json.loads(op.read_text(encoding="utf-8-sig"))
        rows = od if isinstance(od, list) else od.get("stocks") or od.get("pool") or []
        exploded = next(
            (s for s in rows if str(s.get("code") or "").zfill(6) == "001896"),
            None,
        )
    if exploded:
        print(
            f"{d} 炸板 换手={exploded.get('turnover_rate')} "
            f"涨跌={exploded.get('change_rate')} 开板={exploded.get('open_count')} "
            f"首封={exploded.get('first_limit_time')}"
        )
    else:
        print(f"{d} 不在涨停/炸板池 全场最高{data.get('max_board')} 涨停{data.get('count')}")

print()
for d in ("2026-02-27", "2026-03-02"):
    data = load(d)
    info = sent(d)
    print("=" * 8, d, "=" * 8)
    print(
        "涨停",
        data.get("count"),
        "最高",
        data.get("max_board"),
        data.get("board_counts"),
        "跌停",
        info.get("DT"),
        "情绪",
        info.get("sign"),
        "上涨/下跌",
        info.get("SZJS"),
        info.get("XDJS"),
    )
    print("主标签", Counter(str(s.get("theme") or "?") for s in data.get("stocks") or []).most_common(16))
    print("-- 2板及以上 --")
    rows = sorted(
        data.get("stocks") or [],
        key=lambda s: (-int(s.get("boards") or 0), ts(s.get("first_limit_ts"))),
    )
    for s in rows:
        if int(s.get("boards") or 0) < 2:
            continue
        print(
            f"  {s.get('name')} {s.get('boards')}板 {s.get('boards_desc') or ''} "
            f"主题={s.get('theme')} 属性={tags_of(s)} 换手={s.get('turnover_rate')} "
            f"首封={ts(s.get('first_limit_ts'))}"
        )
    print()
