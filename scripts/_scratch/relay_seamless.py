import json
from pathlib import Path

ROOT = Path("data/kaipanla/raw")
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


def streak_start(code, buy):
    if buy not in didx:
        return None, None
    i = didx[buy]
    first = buy
    boards = None
    while i >= 0:
        hit = find(load(days[i]), code)
        if not hit:
            break
        first = days[i]
        boards = hit.get("boards")
        i -= 1
    return first, boards


def theme_count(day, theme):
    data = load(day)
    if not data:
        return 0, None
    n = sum(1 for s in data.get("stocks") or [] if s.get("theme") == theme)
    return n, data.get("max_board")


print(
    f"{'from':<8} {'to':<8} {'prev_duan':<10} {'next_buy':<10} "
    f"{'gap':>3} {'next_born':<10} {'born_vs_duan':<12} "
    f"{'from_th':<8} {'to_th':<8} {'to_n':>4} {'H':>3}"
)

for i, (code, name, buy, duan) in enumerate(trades[:-1]):
    ncode, nname, nbuy, nduan = trades[i + 1]
    born, _ = streak_start(ncode, nbuy)
    ns = find(load(nbuy), ncode)
    ntheme = (ns.get("theme") or "") if ns else ""
    ps = find(load(buy), code)
    ptheme = (ps.get("theme") or "") if ps else ""
    n_same, H = theme_count(nbuy, ntheme)
    g = didx[nbuy] - didx[duan] if duan in didx and nbuy in didx else None
    if born and duan in didx and born in didx:
        rel = didx[born] - didx[duan]
        if rel < 0:
            rel_s = f"早{abs(rel)}日"
        elif rel == 0:
            rel_s = "断日出生"
        else:
            rel_s = f"晚{rel}日"
    else:
        rel_s = "?"
    same_pool = "同池" if ptheme and ptheme == ntheme else "换池"
    print(
        f"{name:<8} {nname:<8} {duan} {nbuy} {str(g):>3} {born or '-':<10} "
        f"{rel_s:<12} {ptheme:<8} {ntheme:<8} {n_same:>4} {str(H):>3} {same_pool}"
    )
