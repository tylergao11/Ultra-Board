import json
from collections import Counter
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


def sector_key(yizi_day, s):
    code = str(s.get("code")).zfill(6)
    sec = s.get("sector_code") or ""
    i = didx[yizi_day]
    prev = days[i - 1]
    n0 = scount(prev, sec)
    if n0 == 0:
        prev_s = find(prev, code)
        old = (prev_s.get("sector_code") or "") if prev_s else ""
        if old and old != sec:
            return old, sec
    return sec, sec


def leaders(day, pred):
    rows = [s for s in slist(day) if pred(s)]
    if not rows:
        return 0, []
    h = max(s.get("boards") or 0 for s in rows)
    return h, [s for s in rows if (s.get("boards") or 0) == h]


def all_dead(yizi_day, tops):
    today = {str(s.get("code")).zfill(6) for s in slist(yizi_day)}
    return all(str(s.get("code")).zfill(6) not in today for s in tops)


def zb_row(day, code):
    if day not in _zb:
        p = ZB / f"{day}.json"
        _zb[day] = None if not p.exists() else {
            str(x.get("code")).zfill(6): x
            for x in json.loads(p.read_text(encoding="utf-8")).get("stocks") or []
        }
    book = _zb[day]
    return None if book is None else book.get(code)


def ths_row(day, code):
    if day not in _ths:
        p = THS / f"{day}.json"
        _ths[day] = None if not p.exists() else {
            str(x.get("code")).zfill(6): x
            for x in json.loads(p.read_text(encoding="utf-8")).get("stocks") or []
        }
    book = _ths[day]
    return None if book is None else book.get(code)


def base_ok(yizi_day, s):
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
    prev_sec, today_sec = sector_key(yizi_day, s)
    n0, n1 = scount(prev, prev_sec), scount(yizi_day, today_sec)
    if n1 >= n0:
        return None
    if any(
        (x.get("sector_code") or "") == today_sec
        and str(x.get("code")).zfill(6) != code
        and is_yizi(x)
        and (x.get("boards") or 0) > (s.get("boards") or 0)
        for x in slist(yizi_day)
    ):
        return None

    def ten_cm(x):
        c = str(x.get("code")).zfill(6)
        return main_board(c) and not is_st(x.get("name") or "")

    h_mkt, mkt_tops = leaders(prev, ten_cm)
    mkt_dead = all_dead(yizi_day, mkt_tops)
    h_sec, sec_tops = leaders(prev, lambda x: (x.get("sector_code") or "") == prev_sec)
    sec_dead = all_dead(yizi_day, sec_tops) if sec_tops else False
    return {
        "code": code, "name": name, "yizi": yizi_day, "buy": nxt,
        "boards": s.get("boards"), "theme": s.get("theme"),
        "n0": n0, "n1": n1, "h_mkt": h_mkt, "mkt_dead": mkt_dead,
        "h_sec": h_sec, "sec_dead": sec_dead,
        "sec_tops": ",".join(x.get("name") or "" for x in sec_tops),
    }


def classify(row):
    day, code = row["buy"], row["code"]
    if day < ZB_START or not (ZB / f"{day}.json").exists():
        return None
    kpl = find(day, code)
    zb = zb_row(day, code)
    ths = ths_row(day, code)
    first, turn, opens, one_price = "", None, None, None
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
        return False, False
    if sealed:
        return True, True
    if zb is not None:
        if yizi_open and (opens is None or opens <= 1):
            return False, False
        return True, False
    return False, False


def chi2(a_ok, a_n, b_ok, b_n):
    # 2x2 chi-square without Yates
    a_no, b_no = a_n - a_ok, b_n - b_ok
    n = a_n + b_n
    if n == 0 or a_n == 0 or b_n == 0:
        return None
    r1, r2 = a_ok + b_ok, a_no + b_no
    if r1 == 0 or r2 == 0:
        return None
    exp = [
        r1 * a_n / n, r2 * a_n / n,
        r1 * b_n / n, r2 * b_n / n,
    ]
    obs = [a_ok, a_no, b_ok, b_no]
    if min(exp) < 5:
        return f"期望格子<5，差不可靠"
    x = sum((o - e) ** 2 / e for o, e in zip(obs, exp))
    return f"chi2={x:.2f}（3.84才到5%）"


cands = []
for d in days[1:-1]:
    for s in slist(d):
        row = base_ok(d, s)
        if row:
            cands.append(row)

buyable = []
for r in cands:
    tag = classify(r)
    if tag is None:
        continue
    can, seal = tag
    if can:
        r = dict(r)
        r["sealed"] = seal
        buyable.append(r)


def show(xs, title):
    ok = sum(1 for r in xs if r["sealed"])
    print(f"{title}: {ok}/{len(xs)} = {ok/len(xs):.1%}" if xs else f"{title}: 0")
    return ok, len(xs)


print(f"可买样本 {len(buyable)}  （原条件，有炸板窗口）")
show(buyable, "全部")
print()
a_ok, a_n = show([r for r in buyable if r["mkt_dead"]], "全场10CM最高板断")
b_ok, b_n = show([r for r in buyable if not r["mkt_dead"]], "全场10CM最高板还在")
print("  ", chi2(a_ok, a_n, b_ok, b_n))
print()
c_ok, c_n = show([r for r in buyable if r["sec_dead"]], "同板块最高板断  ←这才是叠加")
d_ok, d_n = show([r for r in buyable if not r["sec_dead"]], "同板块最高板还在")
print("  ", chi2(c_ok, c_n, d_ok, d_n))
print()
print("按一字日全场10CM高度切开")
for lo, hi, lab in ((0, 4, "昨H<=4"), (5, 7, "昨H5-7"), (8, 99, "昨H>=8")):
    xs = [r for r in buyable if lo <= r["h_mkt"] <= hi]
    show(xs, f"  {lab}")
print()
print("按同板块昨高切开")
for lo, hi, lab in ((1, 2, "板块昨H<=2"), (3, 4, "板块昨H3-4"), (5, 99, "板块昨H>=5")):
    xs = [r for r in buyable if lo <= r["h_sec"] <= hi]
    show(xs, f"  {lab}")
