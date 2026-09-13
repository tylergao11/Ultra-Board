import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("data/kaipanla/raw")
TZ = timezone(timedelta(hours=8))
days = sorted(
    p.name
    for p in ROOT.iterdir()
    if p.is_dir() and (p / "zt_pool.json").exists()
)
didx = {d: i for i, d in enumerate(days)}

trades = [
    ("001379", "腾达科技", "2024-07-30", "2024-08-06"),
    ("600326", "西藏天路", "2024-08-15", "2024-08-16"),
    ("000062", "深圳华强", "2024-08-20", "2024-08-29"),
    ("002302", "西部建设", "2024-08-27", "2024-08-30"),
    ("603626", "科森科技", "2024-09-03", "2024-09-09"),
    ("000566", "海南海药", "2024-09-11", "2024-09-18"),
    ("002583", "海能达", "2024-09-25", "2024-09-27"),
    ("600881", "亚泰集团", "2024-09-26", "2024-10-09"),
    ("002628", "成都路桥", "2024-10-18", "2024-10-24"),
    ("002542", "中化岩土", "2024-10-30", "2024-11-08"),
    ("000833", "粤桂股份", "2024-11-15", "2024-11-26"),
    ("002348", "高乐股份", "2024-11-26", "2024-11-27"),
    ("002730", "电光科技", "2024-12-25", "2024-12-30"),
    ("000533", "顺钠股份", "2025-01-02", "2025-01-06"),
    ("002917", "金奥博", "2025-01-13", "2025-01-20"),
    ("603928", "兴业股份", "2025-01-22", "2025-01-27"),
    ("605398", "新炬网络", "2025-02-05", "2025-02-13"),
    ("601177", "杭齿前进", "2025-02-14", "2025-02-24"),
    ("002522", "浙江众成", "2025-02-24", "2025-02-25"),
    ("002910", "庄园牧场", "2025-02-26", "2025-02-28"),
    ("603700", "宁水集团", "2025-03-05", "2025-03-07"),
    ("000665", "湖北广电", "2025-03-10", "2025-03-13"),
    ("603677", "奇精机械", "2025-03-13", "2025-03-21"),
    ("002278", "神开股份", "2025-03-20", "2025-03-24"),
    ("002767", "先锋电子", "2025-03-24", "2025-03-26"),
    ("002549", "凯美特气", "2025-04-01", "2025-04-03"),
]


def load(day):
    p = ROOT / day / "zt_pool.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def find(data, code):
    if not data:
        return None
    for s in data.get("stocks") or []:
        if str(s.get("code")).zfill(6) == code:
            return s
    return None


def hhmm(ts):
    if not ts:
        return "-"
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M")


def theme_stats(day, theme):
    data = load(day)
    if not data:
        return 0, 0, None, None
    members = [s for s in data.get("stocks") or [] if s.get("theme") == theme]
    max_b = max((s.get("boards") or 0) for s in members) if members else 0
    return len(members), max_b, data.get("max_board"), data.get("count")


def streak(code, buy):
    if buy not in didx:
        return None
    i = didx[buy]
    first = buy
    while i >= 0:
        hit = find(load(days[i]), code)
        if not hit:
            break
        first = days[i]
        i -= 1
    return first


def trail(code, start, end):
    if start not in didx:
        return []
    stop = didx.get(end, didx[start])
    out = []
    for d in days[didx[start] : stop + 1]:
        hit = find(load(d), code)
        if hit:
            out.append(
                f"{d} {hit.get('boards')}板 {hit.get('turnover_rate')}% "
                f"首封{hhmm(hit.get('first_limit_ts'))} {hit.get('theme')}"
            )
    return out


for i, (code, name, buy, duan) in enumerate(trades[:-1]):
    ncode, nname, nbuy, nduan = trades[i + 1]
    ps = find(load(buy), code)
    ns = find(load(nbuy), ncode)
    ptheme = (ps or {}).get("theme")
    ntheme = (ns or {}).get("theme")
    last = None
    last_s = None
    if duan in didx:
        for d in days[didx[buy] : didx[duan] + 1]:
            hit = find(load(d), code)
            if hit:
                last, last_s = d, hit
    pn, pb, pH, pnzt = theme_stats(last or buy, ptheme)
    # theme on last zt day vs duan day
    duan_data = load(duan)
    nn, nb, nH, nnzt = theme_stats(nbuy, ntheme)
    born = streak(ncode, nbuy)
    g = didx.get(nbuy, 0) - didx.get(duan, 0)
    print("=" * 72)
    print(f"{name} {buy} -> {nname} {nbuy}   gap={g}  换池={ptheme}→{ntheme}")
    print(f"  旧票最后涨停 {last} {None if not last_s else last_s.get('boards')}板 换手{None if not last_s else last_s.get('turnover_rate')} 首封{hhmm((last_s or {}).get('first_limit_ts'))}")
    print(f"  旧池在最后涨停日: {ptheme} {pn}只 最高{pb}  全场H={pH} 涨停{pnzt}")
    if duan_data:
        d_n, d_b, dH, dnzt = theme_stats(duan, ptheme)
        print(f"  旧票断板日 {duan}: 旧池还剩{d_n}只 池最高{d_b}  全场H={dH} 涨停{dnzt}")
    print(f"  新票出生 {born}  买日{ns.get('boards') if ns else None}板 换手{ns.get('turnover_rate') if ns else None} 首封{hhmm((ns or {}).get('first_limit_ts'))}")
    print(f"  新池在买日: {ntheme} {nn}只 最高{nb}  全场H={nH} 涨停{nnzt}")
    print("  新票持有轨迹:")
    for line in trail(ncode, nbuy, nduan):
        print("   ", line)
