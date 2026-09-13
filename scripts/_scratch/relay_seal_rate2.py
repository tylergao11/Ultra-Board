import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("data/kaipanla/raw")
ZB = Path("data/ths/open_limit_pool")
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
_zt = {}
_zb = {}


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
    if hhmm(s.get("first_limit_ts")) != "09:25":
        return False
    t = s.get("turnover_rate")
    return t is not None and t <= YIZI_TURN


def find(day, code):
    for s in slist(day):
        if str(s.get("code")).zfill(6) == code:
            return s
    return None


def scount(day, sec):
    if not sec:
        return 0
    return sum(1 for s in slist(day) if (s.get("sector_code") or "") == sec)


def zbset(day):
    if day in _zb:
        return _zb[day]
    p = ZB / f"{day}.json"
    if not p.exists():
        _zb[day] = None
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    _zb[day] = {str(s.get("code")).zfill(6) for s in data.get("stocks") or []}
    return _zb[day]


def judge(yizi_day, s):
    code = str(s.get("code")).zfill(6)
    name = s.get("name") or ""
    if not main_board(code) or is_st(name):
        return None
    if (s.get("boards") or 0) < 2:
        return None
    if not is_yizi(s):
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
    hats = [
        x.get("name")
        for x in slist(yizi_day)
        if (x.get("sector_code") or "") == sec
        and str(x.get("code")).zfill(6) != code
        and is_yizi(x)
        and (x.get("boards") or 0) > (s.get("boards") or 0)
    ]
    if hats:
        return None
    return {
        "code": code,
        "name": name,
        "yizi": yizi_day,
        "buy": nxt,
        "boards": s.get("boards"),
        "theme": s.get("theme"),
        "sec": sec,
        "n0": n0,
        "n1": n1,
        "turn": s.get("turnover_rate"),
    }


def outcome(row):
    nxt, code = row["buy"], row["code"]
    sealed = find(nxt, code) is not None
    zb = zbset(nxt)
    touched = sealed or (zb is not None and code in zb)
    return sealed, touched, zb is not None


print("口径：沪深10CM主板，非ST，2板及以上")
print("一字=09:25且换手<=6.5%；板块=开盘啦sector_code（只在新代码昨日为0时，才按个股旧代码算改名）")
print("降级=一字日板块家数 < 前一日；头顶=同代码里没有更高板的一字")
print("摸板=次日涨停池或炸板池；封死=次日收盘在涨停池")
print("炸板从2025-08-27才能看见，之前的日子不混进封死率")
print()

print("==== 你的26笔一字日是否进样本 ====")
for code, name, buy in TRADES:
    i = didx[buy]
    yizi_day = days[i - 1]
    s = find(yizi_day, code)
    if not s:
        print(f"  {name} {yizi_day} 不在池")
        continue
    row = judge(yizi_day, s)
    why = []
    if not is_yizi(s):
        why.append(f"不是一字(首封{hhmm(s.get('first_limit_ts'))} 换手{s.get('turnover_rate')})")
    sec = s.get("sector_code") or ""
    prev = days[i - 2]
    n1 = scount(yizi_day, sec)
    n0 = scount(prev, sec)
    if n0 == 0:
        prev_s = find(prev, code)
        old = (prev_s.get("sector_code") or "") if prev_s else ""
        if old and old != sec:
            n0 = scount(prev, old)
    if n1 >= n0:
        why.append(f"板块未降{n0}->{n1}")
    hats = [
        x.get("name")
        for x in slist(yizi_day)
        if (x.get("sector_code") or "") == sec
        and str(x.get("code")).zfill(6) != code
        and is_yizi(x)
        and (x.get("boards") or 0) > (s.get("boards") or 0)
    ]
    if hats:
        why.append(f"头顶{hats}")
    print(f"  {name} {yizi_day} {s.get('boards')}板 {s.get('theme')} {n0}->{n1}  "
          + ("进样本" if row else "剔掉：" + "；".join(why)))

cands = []
for d in days[1:-1]:
    for s in slist(d):
        row = judge(d, s)
        if row:
            cands.append(row)

print(f"\n条件1样本 {len(cands)} 笔  {cands[0]['yizi'] if cands else ''} ~ {cands[-1]['yizi'] if cands else ''}")


def summarize(rows, title):
    sealed = touched = unknown = no_touch = 0
    fails = []
    for r in rows:
        seal, touch, has_zb = outcome(r)
        if not has_zb:
            unknown += 1
            continue
        if not touch:
            no_touch += 1
            continue
        touched += 1
        if seal:
            sealed += 1
        else:
            fails.append(r)
    print(f"\n{title}")
    print(f"  有炸板可判定: 未摸板{no_touch}  摸板{touched}  封死{sealed}  "
          f"封死/摸板={sealed/touched:.1%}" if touched else f"  有炸板可判定: 摸板0")
    if touched:
        print(f"  摸板/可判定={(touched)/(touched+no_touch):.1%}  （{touched}/{touched+no_touch}）")
    print(f"  无炸板、不进封死率: {unknown}")
    if fails[:8]:
        print("  摸了没封例如:")
        for r in fails[:8]:
            print(f"    {r['buy']} {r['name']} {r['boards']}板 {r['theme']} 前日板块{r['n0']}->{r['n1']}")


with_zb = [r for r in cands if r["buy"] >= ZB_START]
pre = [r for r in cands if r["buy"] < ZB_START]
summarize(cands, "全部（封死率只走有炸板的次日）")
summarize([r for r in with_zb if r["boards"] >= 2], "2025-08-27起 2板+一字")
summarize([r for r in with_zb if r["boards"] >= 3], "2025-08-27起 3板+一字")

pre_seal = sum(1 for r in pre if find(r["buy"], r["code"]))
print(f"\n2024-07~2025-08-26 条件1={len(pre)} 次日收盘仍涨停={pre_seal} "
      f"占比{pre_seal/len(pre):.1%}（没有炸板，不能当成封死/摸板）")
