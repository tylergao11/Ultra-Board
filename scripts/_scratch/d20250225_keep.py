# -*- coding: utf-8 -*-
import json
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CN = timezone(timedelta(hours=8))
ROOT = Path(r"C:\Ai\Ultra-Board\data\kaipanla\raw")
WANT = {
    "002527": "新时达",
    "600590": "泰豪科技",
    "600589": "大位科技",
    "002910": "庄园牧场",
    "600602": "云赛智联",
    "600825": "新华传媒",
    "000892": "欢瑞世纪",
}


def ts(v):
    if not v:
        return ""
    return datetime.fromtimestamp(int(v), CN).strftime("%H:%M")


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
    ok = first.startswith("09:25") and to <= 6.5 and oc in (0, None, 0)
    return ok, first, oc, to


def load(day):
    p = ROOT / day / "zt_pool.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


days = sorted(p.name for p in ROOT.iterdir() if p.is_dir() and p.name >= "2025-02-24" and p.name <= "2025-03-10")
print("days", days)

for d in days:
    data = load(d)
    if not data:
        continue
    stocks = data.get("stocks") or []
    by = {str(s.get("code") or "").zfill(6): s for s in stocks}
    print("=" * 8, d, "涨停", data.get("count"), "最高", data.get("max_board"), "=" * 8)
    print("主标签", Counter(str(s.get("theme") or "?") for s in stocks).most_common(8))
    for code, name in WANT.items():
        s = by.get(code)
        if not s:
            print(f"  {name} 不在")
            continue
        ok, first, oc, to = yizi(s)
        print(
            f"  {name} {s.get('boards')}板 {'一字' if ok else '开/松'} "
            f"主题={s.get('theme')} 换手={to} 开板={oc} 首封={first} "
            f"实空={s.get('real_space')}"
        )

print("\n--- 2.25 一字全场 ---")
data = load("2025-02-25")
for s in data.get("stocks") or []:
    ok, first, oc, to = yizi(s)
    if ok:
        print(
            f"  {s.get('name')} {s.get('code')} {s.get('boards')}板 主题={s.get('theme')} "
            f"换手={to} 实空={s.get('real_space')}"
        )
