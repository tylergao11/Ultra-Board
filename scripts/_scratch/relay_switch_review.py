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


def gap(a, b):
    if a not in didx or b not in didx:
        return None
    return didx[b] - didx[a]


def last_zt(code, buy, duan):
    last_day = None
    last_boards = None
    if buy not in didx:
        return None, None
    end = didx.get(duan, didx[buy])
    for d in days[didx[buy] : end + 1]:
        hit = find(load(d), code)
        if hit:
            last_day = d
            last_boards = hit.get("boards")
    return last_day, last_boards


print(
    f"{'name':<8} {'buy':<10} {'duan':<10} {'next':<10} {'switch':<10} "
    f"{'g_dn':>4} {'buyB':>4} {'lastB':>5} {'extra':>5} {'theme':<8} {'H':>3} {'nzt':>4}"
)

for i, (code, name, buy, duan) in enumerate(trades):
    nxt = trades[i + 1][2] if i + 1 < len(trades) else None
    data_b = load(buy)
    s = find(data_b, code)
    buy_b = s.get("boards") if s else None
    theme = (s.get("theme") or "") if s else ""
    last_day, last_b = last_zt(code, buy, duan)
    extra = None
    if buy_b is not None and last_b is not None:
        extra = last_b - buy_b
    if nxt is None:
        kind = "end"
        g = None
    elif nxt < duan:
        kind = "early"
        g = gap(nxt, duan)
    elif nxt == duan:
        kind = "duan_day"
        g = 0
    else:
        kind = "after"
        g = gap(duan, nxt)
    H = data_b.get("max_board") if data_b else None
    nzt = data_b.get("count") if data_b else None
    print(
        f"{name:<8} {buy} {duan} {nxt or '-':<10} {kind:<10} "
        f"{str(g) if g is not None else '-':>4} {str(buy_b):>4} {str(last_b):>5} "
        f"{str(extra):>5} {theme:<8} {str(H):>3} {str(nzt):>4}"
    )

print("\n--- buy-day vs prev last-zt / overlap ---")
for i, (code, name, buy, duan) in enumerate(trades[:-1]):
    ncode, nname, nbuy, nduan = trades[i + 1]
    prev_last, prev_last_b = last_zt(code, buy, duan)
    still = None
    if nbuy in didx and nbuy <= duan:
        still = find(load(nbuy), code)
    print(
        f"{name} last_zt={prev_last} {prev_last_b}板 -> {nname} {nbuy} "
        f"prev_still_zt={bool(still)} next_duan={nduan}"
    )
