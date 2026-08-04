import sys
from pathlib import Path
from collections import Counter, defaultdict
sys.path.insert(0, "scripts/_scratch")
from ferment_open_seal_grid import build_rows
from reverse_zhaban_top_open import keep_top_open_per_group
import importlib.util
spec = importlib.util.spec_from_file_location("bt", "scripts/_scratch/backtest_main_ladder.py")
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

days, pools, pools_m = bt.load_days()
raw = build_rows(days, pools, pools_m)
kept, _ = keep_top_open_per_group(raw)

# after drop ferment water
remain = [r for r in kept if not (r["fb"] >= 3 and r["open_pct_T1"] < 0)]
touch = [r for r in remain if r["touched"]]
zha = [r for r in touch if r["zhaban"]]
seal = [r for r in touch if r["sealed"]]

print("删发酵水下后 摸板", len(touch), "炸", len(zha), "封", len(seal))
print("炸板率", len(zha)/len(touch))
print()

# user cases
names = ["澄星", "神州", "华升"]
print("=== 用户点名 ===")
for r in kept:
    if any(n in r["name"] for n in names):
        tag = "炸" if r["zhaban"] else ("封" if r["sealed"] else "未摸")
        print(
            r["T"], r["name"], f"{r['boards_T']}板",
            f"fb={r['fb']}", f"open={r['open_pct_T1']:.2f}%",
            f"yizi={r['yizi']}", f"amt={r['amount_yi']}",
            f"theme={r['theme']}", tag,
            "发酵水下" if (r["fb"]>=3 and r["open_pct_T1"]<0) else "",
        )

print()
print("=== 剩余28炸板全表 ===")
for r in sorted(zha, key=lambda x: (-x["open_pct_T1"], x["T"])):
    print(
        f"{r['T']} {r['name']:8s} {r['boards_T']}板 fb={r['fb']:2d} "
        f"open={r['open_pct_T1']:6.2f}% yizi={str(r['yizi']):5s} "
        f"amt={str(r['amount_yi']):6s} {r['theme']}"
    )

# pattern mining on remaining zha
def open_b(x):
    if x < 0: return "水下<0"
    if x < 2: return "[0,2)"
    if x < 5: return "[2,5)"
    if x < 8: return "[5,8)"
    if x < 9.5: return "[8,9.5)"
    return "近板≥9.5"

def patterns(rows, label):
    print(f"\n=== {label} 分布 (n={len(rows)}) ===")
    for title, fn in [
        ("开盘", lambda r: open_b(r["open_pct_T1"])),
        ("fb", lambda r: f"fb={r['fb']}" if r["fb"]<=5 else "fb>=6"),
        ("板高", lambda r: f"{r['boards_T']}板"),
        ("一字", lambda r: "一字" if r["yizi"] else "换手"),
        ("额", lambda r: "<3亿" if (r["amount_yi"] or 0)<3 else ("3-10亿" if (r["amount_yi"] or 0)<10 else ">=10亿")),
    ]:
        c = Counter(fn(r) for r in rows)
        print(title, dict(c.most_common()))

patterns(zha, "剩余炸板")
patterns(seal, "剩余封板对照")

# zhaban rate by cell among remain touch
print("\n=== 剩余摸板 各格炸板率 n>=3 ===")
cells = []
for r in touch:
    key = (
        "一字" if r["yizi"] else "换手",
        f"{r['boards_T']}板" if r["boards_T"]<=4 else ">=5板",
        open_b(r["open_pct_T1"]),
        "fb0" if r["fb"]==0 else ("fb1-2" if r["fb"]<=2 else ("fb3-5" if r["fb"]<=5 else "fb>=6")),
    )
    cells.append((key, r["zhaban"]))

from collections import defaultdict
g = defaultdict(list)
for k, z in cells:
    g[k].append(z)
risk = []
for k, zs in g.items():
    if len(zs) < 3:
        continue
    rate = sum(zs)/len(zs)
    risk.append((rate, len(zs), sum(zs), k))
risk.sort(reverse=True)
print("最高炸板率格子:")
for rate, n, nz, k in risk[:12]:
    print(f"  {rate:.0%} n={n} 炸{nz} | {k}")
print("最低:")
for rate, n, nz, k in sorted(risk, key=lambda x: (x[0], -x[1]))[:8]:
    print(f"  {rate:.0%} n={n} 炸{nz} | {k}")

# special: 近板一字 小额?
print("\n=== 近板≥9.5 子集 ===")
near = [r for r in touch if r["open_pct_T1"]>=9.5]
print("摸", len(near), "炸", sum(1 for r in near if r["zhaban"]), 
      f"炸板率{sum(1 for r in near if r['zhaban'])/len(near):.1%}" if near else "")
near_z = [r for r in near if r["zhaban"]]
for r in near_z:
    print(f"  炸 {r['name']} {r['boards_T']}板 fb={r['fb']} yizi={r['yizi']} amt={r['amount_yi']} {r['theme']}")

print("\n=== 一字 子集 ===")
yz = [r for r in touch if r["yizi"]]
print("摸", len(yz), "炸", sum(1 for r in yz if r["zhaban"]),
      f"率{sum(1 for r in yz if r['zhaban'])/len(yz):.1%}" if yz else "")
for r in yz:
    if r["zhaban"]:
        print(f"  炸 {r['name']} open={r['open_pct_T1']:.1f} amt={r['amount_yi']} {r['boards_T']}板 fb={r['fb']}")

print("\n=== 4板 子集 ===")
b4 = [r for r in touch if r["boards_T"]==4]
print("摸", len(b4), "炸", sum(1 for r in b4 if r["zhaban"]),
      f"率{sum(1 for r in b4 if r['zhaban'])/len(b4):.1%}" if b4 else "")
