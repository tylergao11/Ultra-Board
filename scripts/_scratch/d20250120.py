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
NAMES = ("先锋电子", "瀛通通讯", "德联集团", "兴业股份", "远程股份", "华脉科技")


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


def show(s):
    is_yz, first, oc, to = yizi(s)
    print(
        f"  {s.get('name')} {s.get('code')} {s.get('boards')}板 {s.get('boards_desc') or ''} "
        f"{'一字' if is_yz else ''} 主题={s.get('theme')} 属性={tags_of(s)} "
        f"换手={to} 首封={first} 开板={oc} "
        f"开={s.get('open')} 低={s.get('low')} 开幅={s.get('open_pct')}"
    )


def trail(code, days):
    for d in days:
        p = ROOT / d / "zt_pool.json"
        if not p.exists():
            print(f"  {d} NO FILE")
            continue
        data = load(d)
        hit = next((s for s in data.get("stocks") or [] if str(s.get("code")).zfill(6) == code), None)
        if hit:
            is_yz, first, oc, to = yizi(hit)
            print(
                f"  {d} 在池 {hit.get('boards')} {hit.get('boards_desc') or ''} "
                f"{'一字' if is_yz else ''} 主题={hit.get('theme')} 属性={tags_of(hit)} "
                f"换手={to} 首封={first} 开板={oc} "
                f"最高{data.get('max_board')} 涨停{data.get('count')}"
            )
            continue
        exploded = None
        op = THS / f"{d}.json"
        if op.exists():
            od = json.loads(op.read_text(encoding="utf-8-sig"))
            rows = od if isinstance(od, list) else od.get("stocks") or od.get("pool") or []
            exploded = next((s for s in rows if str(s.get("code") or "").zfill(6) == code), None)
        if exploded:
            print(
                f"  {d} 炸板 换手={exploded.get('turnover_rate')} 涨跌={exploded.get('change_rate')} "
                f"开板={exploded.get('open_count')} 首封={exploded.get('first_limit_time')} "
                f"最高{data.get('max_board')} 涨停{data.get('count')}"
            )
        else:
            print(f"  {d} 不在 最高{data.get('max_board')} 涨停{data.get('count')}")


days = ["2025-01-16", "2025-01-17", "2025-01-20", "2025-01-21"]
codes = {}
for d in days:
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        continue
    for s in load(d).get("stocks") or []:
        if s.get("name") in NAMES:
            codes[s.get("name")] = str(s.get("code")).zfill(6)

print("codes", codes)
for name in NAMES:
    print(f"==== {name} {codes.get(name)} ====")
    if codes.get(name):
        trail(codes[name], days)
    else:
        print("  这几天池子里没找到")

for d in ("2025-01-17", "2025-01-20"):
    data = load(d)
    stocks = data.get("stocks") or []
    print()
    print("=" * 8, d, "涨停", data.get("count"), "最高", data.get("max_board"), data.get("board_counts"), "=" * 8)
    print("主标签", Counter(str(s.get("theme") or "?") for s in stocks).most_common(12))
    print("-- 点名 --")
    for s in stocks:
        if s.get("name") in NAMES:
            show(s)
    print("-- 2板+ --")
    for s in sorted(stocks, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        if int(s.get("boards") or 0) < 2:
            continue
        show(s)
    print("-- 一字 --")
    for s in sorted(stocks, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        if yizi(s)[0]:
            show(s)
