import runpy
from collections import Counter
from pathlib import Path

# reuse functions
ns = runpy.run_path("scripts/_scratch/relay_seal_height.py")
days = ns["days"]
slist = ns["slist"]
judge = ns["judge"]
classify = ns["classify"]
height_broke = ns["height_broke"]

cands = []
for d in days[1:-1]:
    for s in slist(d):
        row = judge(d, s, False)
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


def rate(xs, title):
    ok = [r for r in xs if r["sealed"]]
    print(f"{title}  可买{len(xs)} 封死{len(ok)}  {len(ok)/len(xs):.1%}" if xs else f"{title}  0")
    fails = [r for r in xs if not r["sealed"]]
    if fails:
        print("  没封:", ", ".join(f"{r['buy']}{r['name']}{r['boards']}板/{r['theme']}" for r in fails))


print("同一套可买口径，只按一字日最高板是否断切开\n")
rate(buyable, "全部可买")
rate([r for r in buyable if r["broke"]], "一字日10CM最高板断了")
rate([r for r in buyable if not r["broke"]], "一字日10CM最高板还在")
print()
print("断了且可买的去向", Counter(r["tag"] for r in buyable if r["broke"]))
print("没断且可买的去向", Counter(r["tag"] for r in buyable if not r["broke"]))
print()
print("断了且封死的:")
for r in buyable:
    if r["broke"] and r["sealed"]:
        print(f"  {r['buy']} {r['name']} {r['boards']}板 {r['theme']} {r['tag']} 昨H{r['h0']}->今H{r['h1']}")
