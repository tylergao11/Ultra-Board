# -*- coding: utf-8 -*-
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CN = timezone(timedelta(hours=8))
ROOT = Path(r"C:\Ai\Ultra-Board\data\kaipanla\raw")
THS = Path(r"C:\Ai\Ultra-Board\data\ths\open_limit_pool")
CODE = "603172"


def ts(v):
    if not v:
        return ""
    return datetime.fromtimestamp(int(v), CN).strftime("%H:%M")


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


days = [
    "2026-01-29",
    "2026-01-30",
    "2026-02-02",
    "2026-02-03",
    "2026-02-04",
    "2026-02-05",
    "2026-02-06",
    "2026-02-09",
    "2026-02-10",
    "2026-02-11",
    "2026-02-12",
    "2026-02-13",
]
for d in days:
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        print(d, "NO FILE")
        continue
    data = json.loads(p.read_text(encoding="utf-8"))
    hit = next((s for s in data.get("stocks") or [] if str(s.get("code")).zfill(6) == CODE), None)
    if hit:
        is_yz, first, oc, to = yizi(hit)
        print(
            f"{d} 在池 {hit.get('boards')} {hit.get('boards_desc') or ''} "
            f"{'一字' if is_yz else ''} 主题={hit.get('theme')} 属性={tags_of(hit)} "
            f"换手={to} 首封={first} 开板={oc} "
            f"开={hit.get('open')} 高={hit.get('high')} 低={hit.get('low')} "
            f"昨收={hit.get('prev_close')} 开幅={hit.get('open_pct')} "
            f"最高{data.get('max_board')} 涨停{data.get('count')}"
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
            f"开板={exploded.get('open_count')} 首封={exploded.get('first_limit_time')} "
            f"最高{data.get('max_board')} 涨停{data.get('count')}"
        )
    else:
        print(f"{d} 不在 最高{data.get('max_board')} 涨停{data.get('count')}")
