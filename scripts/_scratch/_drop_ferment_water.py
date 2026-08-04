import sys
from pathlib import Path
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

def stats(rows, label):
    touch = [r for r in rows if r["touched"]]
    seal = [r for r in touch if r["sealed"]]
    zha = [r for r in touch if r["zhaban"]]
    print(f"=== {label} ===")
    print(f"票次 {len(rows)} 摸板 {len(touch)} 封 {len(seal)} 炸 {len(zha)}")
    if touch:
        print(f"封板率 {len(seal)/len(touch):.1%}  炸板率 {len(zha)/len(touch):.1%}")
    cont = sum(1 for r in rows if r["cont"])
    print(f"连板率 {cont}/{len(rows)}={cont/len(rows):.1%}")
    return touch, seal, zha

print("基线：同梯队同属性开最高")
stats(kept, "基线")

deleted = [r for r in kept if r["fb"] >= 3 and r["open_pct_T1"] < 0]
remain = [r for r in kept if not (r["fb"] >= 3 and r["open_pct_T1"] < 0)]
print()
print(f"删掉 发酵且水下 fb>=3 open<0 : {len(deleted)} 只")
for r in sorted(deleted, key=lambda x: x["T"]):
    if r["zhaban"]:
        t = "炸"
    elif r["sealed"]:
        t = "封"
    elif not r["touched"]:
        t = "未摸"
    else:
        t = "?"
    print(f"  {r['T']} {r['name']} {r['boards_T']}板 fb={r['fb']} open={r['open_pct_T1']:.2f}% {t}")
print()
stats(remain, "删发酵水下后")

# also delete all open<-3 regardless
remain2 = [r for r in remain if r["open_pct_T1"] >= -3]
print()
stats(remain2, "再删全部深水<-3%")
print("相对基线再删", len(remain) - len(remain2))
