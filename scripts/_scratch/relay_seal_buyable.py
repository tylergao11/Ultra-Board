import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("data/kaipanla/raw")
ZB = Path("data/ths/open_limit_pool")
THS = Path("data/ths/limit_pool")
TZ = timezone(timedelta(hours=8))
YIZI_TURN = 6.5
ZB_START = "2025-08-27"

days = sorted(p.name for p in ROOT.iterdir() if (p / "zt_pool.json").exists())
didx = {d: i for i, d in enumerate(days)}
_zt, _zb, _ths = {}, {}, {}


def load_zt(day):
    if day not in _zt:
        _zt[day] = json.loads((ROOT / day / "zt_pool.json").read_text(encoding="utf-8"))
    return _zt[day]


def slist(day):
    return load_zt(day).get("stocks") or []


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else ""


def main_board(code):
    return code.startswith(("000", "001", "002", "003", "600", "601", "603", "605"))


def is_st(name):
    return "ST" in (name or "").upper()


def is_yizi(s):
    return hhmm(s.get("first_limit_ts")) == "09:25" and s.get("turnover_rate") is not None and s.get("turnover_rate") <= YIZI_TURN


def find(day, code):
    for s in slist(day):
        if str(s.get("code")).zfill(6) == code:
            return s
    return None


def scount(day, sec):
    return sum(1 for s in slist(day) if (s.get("sector_code") or "") == sec) if sec else 0


def zb_row(day, code):
    if day not in _zb:
        p = ZB / f"{day}.json"
        if not p.exists():
            _zb[day] = None
        else:
            data = json.loads(p.read_text(encoding="utf-8"))
            _zb[day] = {str(s.get("code")).zfill(6): s for s in data.get("stocks") or []}
    book = _zb[day]
    return None if book is None else book.get(code)


def ths_row(day, code):
    if day not in _ths:
        p = THS / f"{day}.json"
        if not p.exists():
            _ths[day] = None
        else:
            data = json.loads(p.read_text(encoding="utf-8"))
            _ths[day] = {str(s.get("code")).zfill(6): s for s in data.get("stocks") or []}
    book = _ths[day]
    return None if book is None else book.get(code)


def judge(yizi_day, s):
    code = str(s.get("code")).zfill(6)
    name = s.get("name") or ""
    if not main_board(code) or is_st(name) or (s.get("boards") or 0) < 2 or not is_yizi(s):
        return None
    sec = s.get("sector_code") or ""
    if not sec:
        return None
    i = didx[yizi_day]
    if i < 1 or i + 1 >= len(days):
        return None
    prev, nxt = days[i - 1], days[i + 1]
    n1 = scount(yizi_day, sec)
    n0 = scount(prev, sec)
    if n0 == 0:
        prev_s = find(prev, code)
        old = (prev_s.get("sector_code") or "") if prev_s else ""
        if old and old != sec:
            n0 = scount(prev, old)
    if n1 >= n0:
        return None
    if any(
        (x.get("sector_code") or "") == sec
        and str(x.get("code")).zfill(6) != code
        and is_yizi(x)
        and (x.get("boards") or 0) > (s.get("boards") or 0)
        for x in slist(yizi_day)
    ):
        return None
    return {
        "code": code, "name": name, "yizi": yizi_day, "buy": nxt,
        "boards": s.get("boards"), "theme": s.get("theme"), "n0": n0, "n1": n1,
        "turn": s.get("turnover_rate"),
    }


def classify(row):
    """返回 (标签, 可买, 封死). 无炸板日返回 None."""
    day, code = row["buy"], row["code"]
    if day < ZB_START or not (ZB / f"{day}.json").exists():
        return None
    kpl = find(day, code)
    zb = zb_row(day, code)

    ths = ths_row(day, code)
    first = ""
    turn = None
    opens = None
    one_price = None
    if kpl:
        first = hhmm(kpl.get("first_limit_ts"))
        turn = kpl.get("turnover_rate")
    if ths:
        first = first or hhmm(ths.get("first_limit_ts"))
        turn = ths.get("turnover_rate") if turn is None else turn
        opens = ths.get("open_count")
        one_price = ths.get("one_price")
        if ths.get("board_type") == "一字板":
            one_price = True if one_price is None else one_price
    if zb:
        first = first or (zb.get("first_limit_time") or "")[:5]
        opens = zb.get("open_count") if opens is None else opens
        turn = zb.get("turnover_rate") if turn is None else turn

    sealed = kpl is not None
    yizi_open = first == "09:25"
    still_yizi = sealed and (
        one_price is True
        or (yizi_open and (opens == 0 or (turn is not None and turn <= YIZI_TURN and (opens is None or opens == 0))))
    )
    if still_yizi:
        return "次日一字未开，买不到", False, False

    if sealed and yizi_open:
        return "一字开后开板回封", True, True
    if sealed and not yizi_open:
        return "盘中摸板回封", True, True

    if zb is not None:
        if yizi_open and (opens is None or opens <= 1):
            return "一字开后开板、未见再摸", False, False
        if yizi_open and opens >= 2:
            return "一字开后开板再摸再炸", True, False
        return "盘中摸板未封", True, False

    return "次日未摸板", False, False


cands = []
for d in days[1:-1]:
    for s in slist(d):
        row = judge(d, s)
        if row:
            cands.append(row)

rows = []
for r in cands:
    tag = classify(r)
    if tag is None:
        continue
    r = dict(r)
    r["tag"], r["buyable"], r["sealed"] = tag
    rows.append(r)

from collections import Counter
print(f"有炸板窗口可判定 {len(rows)}")
print("去向：")
for k, n in Counter(r["tag"] for r in rows).most_common():
    print(f"  {n:4d}  {k}")

buyable = [r for r in rows if r["buyable"]]
sealed = [r for r in buyable if r["sealed"]]
print()
print(f"可买（一字开则必须开板后再摸）{len(buyable)}")
print(f"封死 {len(sealed)}")
print(f"封死/可买 = {len(sealed)/len(buyable):.1%}" if buyable else "无可买")

for title, pred in (
    ("2板+", lambda r: True),
    ("3板+", lambda r: r["boards"] >= 3),
):
    sub = [r for r in buyable if pred(r)]
    ok = [r for r in sub if r["sealed"]]
    print(f"  {title} 可买{len(sub)} 封死{len(ok)}  {len(ok)/len(sub):.1%}" if sub else f"  {title} 0")
