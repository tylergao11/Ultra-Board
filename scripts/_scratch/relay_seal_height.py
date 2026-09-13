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

TRADES = [
    ("001379", "腾达科技", "2024-07-30"),
    ("600326", "西藏天路", "2024-08-15"),
    ("000062", "深圳华强", "2024-08-20"),
    ("002302", "西部建设", "2024-08-27"),
    ("603626", "科森科技", "2024-09-03"),
    ("000566", "海南海药", "2024-09-11"),
    ("002583", "海能达", "2024-09-25"),
    ("600881", "亚泰集团", "2024-09-26"),
    ("002628", "成都路桥", "2024-10-18"),
    ("002542", "中化岩土", "2024-10-30"),
    ("000833", "粤桂股份", "2024-11-15"),
    ("002348", "高乐股份", "2024-11-27"),
    ("002730", "电光科技", "2024-12-25"),
    ("000533", "顺钠股份", "2025-01-02"),
    ("002917", "金奥博", "2025-01-13"),
    ("603928", "兴业股份", "2025-01-22"),
    ("605398", "新炬网络", "2025-02-05"),
    ("601177", "杭齿前进", "2025-02-14"),
    ("002522", "浙江众成", "2025-02-24"),
    ("002910", "庄园牧场", "2025-02-26"),
    ("603700", "宁水集团", "2025-03-05"),
    ("000665", "湖北广电", "2025-03-10"),
    ("603677", "奇精机械", "2025-03-14"),
    ("002278", "神开股份", "2025-03-20"),
    ("002767", "先锋电子", "2025-03-25"),
    ("002549", "凯美特气", "2025-04-01"),
]

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


def height_leaders(day, ten_cm_only):
    rows = []
    for s in slist(day):
        code = str(s.get("code")).zfill(6)
        if ten_cm_only and (not main_board(code) or is_st(s.get("name") or "")):
            continue
        rows.append(s)
    if not rows:
        return 0, []
    h = max(s.get("boards") or 0 for s in rows)
    tops = [s for s in rows if (s.get("boards") or 0) == h]
    return h, tops


def height_broke(yizi_day, ten_cm_only):
    i = didx[yizi_day]
    prev = days[i - 1]
    h, tops = height_leaders(prev, ten_cm_only)
    if not tops:
        return False, h, 0, []
    today_codes = {str(s.get("code")).zfill(6) for s in slist(yizi_day)}
    dead = []
    live = []
    for s in tops:
        code = str(s.get("code")).zfill(6)
        (live if code in today_codes else dead).append(f"{s.get('name')}{s.get('boards')}板")
    h1, _ = height_leaders(yizi_day, ten_cm_only)
    return len(live) == 0, h, h1, tops


def zb_row(day, code):
    if day not in _zb:
        p = ZB / f"{day}.json"
        _zb[day] = None if not p.exists() else {
            str(s.get("code")).zfill(6): s
            for s in json.loads(p.read_text(encoding="utf-8")).get("stocks") or []
        }
    book = _zb[day]
    return None if book is None else book.get(code)


def ths_row(day, code):
    if day not in _ths:
        p = THS / f"{day}.json"
        _ths[day] = None if not p.exists() else {
            str(s.get("code")).zfill(6): s
            for s in json.loads(p.read_text(encoding="utf-8")).get("stocks") or []
        }
    book = _ths[day]
    return None if book is None else book.get(code)


def judge(yizi_day, s, require_height_break):
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
    broke, h0, h1, _ = height_broke(yizi_day, True)
    if require_height_break and not broke:
        return None
    return {
        "code": code, "name": name, "yizi": yizi_day, "buy": nxt,
        "boards": s.get("boards"), "theme": s.get("theme"), "n0": n0, "n1": n1,
        "h0": h0, "h1": h1, "broke": broke,
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


print("最高板=前一日10CM主板非ST的自然最高连板。断=这些代码一字当天都不在涨停池。")
print()
print("==== 你的一字日：10CM最高板断了没有 ====")
for code, name, buy in TRADES:
    i = didx[buy]
    yizi_day = days[i - 1]
    s = find(yizi_day, code)
    if not s:
        print(f"  {name} {yizi_day} 不在池")
        continue
    broke, h0, h1, tops = height_broke(yizi_day, True)
    names = ",".join(f"{t.get('name')}{t.get('boards')}" for t in tops)
    base = judge(yizi_day, s, False)
    print(
        f"  {name} {yizi_day} {s.get('boards')}板 昨H{h0}({names})->今H{h1} "
        f"{'断' if broke else '没断'}  原条件={'进' if base else '本就剔'}"
    )


def report(require_break, title):
    cands = []
    for d in days[1:-1]:
        for s in slist(d):
            row = judge(d, s, require_break)
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
    buyable = [r for r in rows if r["buyable"]]
    sealed = [r for r in buyable if r["sealed"]]
    print(f"\n{title}")
    print(f"  有炸板可判定{len(rows)}  可买{len(buyable)}  封死{len(sealed)}  "
          + (f"封死/可买={len(sealed)/len(buyable):.1%}" if buyable else "无可买"))
    print("  去向:", dict(Counter(r["tag"] for r in rows)))
    sub3 = [r for r in buyable if r["boards"] >= 3]
    ok3 = [r for r in sub3 if r["sealed"]]
    if sub3:
        print(f"  3板+ 可买{len(sub3)} 封死{len(ok3)}  {len(ok3)/len(sub3):.1%}")


report(False, "原条件（无最高板断）")
report(True, "原条件 + 一字日10CM最高板断")
