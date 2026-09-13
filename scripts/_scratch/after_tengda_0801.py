import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("data/kaipanla/raw")
TZ = timezone(timedelta(hours=8))
YIZI_TURN = 6.5
START, END = "2024-08-01", "2024-08-14"

days = sorted(p.name for p in ROOT.iterdir() if (p / "zt_pool.json").exists())
didx = {d: i for i, d in enumerate(days)}
_zt = {}


def load(d):
    if d not in _zt:
        _zt[d] = json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))
    return _zt[d]


def slist(d):
    return load(d).get("stocks") or []


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def main_board(code):
    return code.startswith(("000", "001", "002", "003", "600", "601", "603", "605"))


def is_st(name):
    return "ST" in (name or "").upper()


def is_yizi(s):
    return hhmm(s.get("first_limit_ts")) == "09:25" and s.get("turnover_rate") is not None and s.get("turnover_rate") <= YIZI_TURN


def scount_main(d, sec):
    return sum(1 for s in slist(d) if (s.get("sector_code") or "") == sec)


def scount_attr(d, key):
    n = 0
    for s in slist(d):
        blob = (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")
        if key and key in blob:
            n += 1
    return n


def find(d, code):
    for s in slist(d):
        if str(s.get("code")).zfill(6) == code:
            return s
    return None


print("卖出日8.1之后，观察日8.01~8.13（买日8.02~8.14）")
print("一字=09:25且换手<=6.5%，2板+，10CM非ST。两套降级都报。次日在涨停池=当时能看到的封死。\n")

for d in days:
    if d < START or d > "2024-08-13":
        continue
    i = didx[d]
    prev, nxt = days[i - 1], days[i + 1]
    data = load(d)
    print(f"### 观察日{d} 全场{data['count']} H={data['max_board']}  →买日{nxt}")
    hits = 0
    for s in slist(d):
        code = str(s.get("code")).zfill(6)
        if not main_board(code) or is_st(s.get("name") or "") or (s.get("boards") or 0) < 2 or not is_yizi(s):
            continue
        if code == "001379":
            continue
        sec = s.get("sector_code") or ""
        theme = s.get("theme") or ""
        n0m, n1m = scount_main(prev, sec), scount_main(d, sec)
        n0a, n1a = scount_attr(prev, theme), scount_attr(d, theme)
        down_m = n1m < n0m
        down_a = n1a < n0a
        nxt_s = find(nxt, code)
        nxt_txt = (
            f"次日{nxt_s['boards']}板 换手{nxt_s['turnover_rate']} 首封{hhmm(nxt_s.get('first_limit_ts'))}"
            if nxt_s else "次日不在涨停池"
        )
        hits += 1
        print(
            f"  {s['name']} {s['boards']}板 {theme} 换手{s['turnover_rate']} "
            f"主{n0m}->{n1m}{'降' if down_m else '平/升'} "
            f"属{n0a}->{n1a}{'降' if down_a else '平/升'}  {nxt_txt}"
        )
    if not hits:
        print("  无2板+一字")
    print()
