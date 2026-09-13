# -*- coding: utf-8 -*-
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CN = timezone(timedelta(hours=8))
ROOT = Path(r"C:\Ai\Ultra-Board\data\kaipanla\raw")
THS = Path(r"C:\Ai\Ultra-Board\data\ths\open_limit_pool")
CODE = "000720"


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


days = [
    "2026-03-23",
    "2026-03-24",
    "2026-03-25",
    "2026-03-26",
    "2026-03-27",
    "2026-03-30",
    "2026-03-31",
    "2026-04-01",
    "2026-04-02",
]
for d in days:
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        print(d, "NO FILE")
        continue
    data = load(d)
    hit = next((s for s in data.get("stocks") or [] if str(s.get("code")).zfill(6) == CODE), None)
    if hit:
        print(
            f"{d} 在池 {hit.get('boards')} {hit.get('boards_desc') or ''} "
            f"主题={hit.get('theme')} 属性={tags_of(hit)} 换手={hit.get('turnover_rate')} "
            f"首封={ts(hit.get('first_limit_ts'))} 开板={oc_of(hit)} 全场最高{data.get('max_board')}"
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
            f"全场最高{data.get('max_board')} 涨停{data.get('count')}"
        )
    else:
        print(f"{d} 不在 最高{data.get('max_board')} 涨停{data.get('count')}")
