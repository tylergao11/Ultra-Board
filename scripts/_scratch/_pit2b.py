import sys
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
remain = [r for r in kept if not (r["fb"] >= 3 and r["open_pct_T1"] < 0)]
touch = [r for r in remain if r["touched"]]

def rate(pred, name):
    sub = [r for r in touch if pred(r)]
    if not sub:
        print(name, "n=0")
        return
    z = sum(1 for r in sub if r["zhaban"])
    print(f"{name}: 摸{len(sub)} 炸{z} 炸板率{z/len(sub):.1%}  其余摸板炸板率{(sum(1 for r in touch if not pred(r) and r['zhaban']))/max(1,sum(1 for r in touch if not pred(r))):.1%}")

# candidate second pits
rate(lambda r: r["boards_T"] >= 4, "A 节点日>=4板")
rate(lambda r: r["boards_T"] == 4, "A2 恰好4板")
rate(lambda r: r["open_pct_T1"] >= 9.5 and r["boards_T"] >= 3, "B 近板且>=3板")
rate(lambda r: r["open_pct_T1"] >= 9.0 and (r["amount_yi"] or 99) < 2, "C 近板且额<2亿")
rate(lambda r: r["yizi"] and (r["amount_yi"] or 99) < 2, "D 一字且额<2亿")
rate(lambda r: r["yizi"] and r["open_pct_T1"] >= 9 and (r["amount_yi"] or 99) < 3, "E 一字近板小额<3亿")
rate(lambda r: 3 <= r["fb"] <= 5 and r["open_pct_T1"] >= 9, "F 中发酵fb3-5且近板")
rate(lambda r: r["open_pct_T1"] >= 9.5 and r["fb"] == 0, "G 未发酵近板")
rate(lambda r: r["boards_T"] >= 4 and r["open_pct_T1"] >= 5, "H >=4板且开>=5%")
rate(lambda r: r["boards_T"] >= 4 and r["yizi"], "I >=4板一字")

# if delete second pit A2 4板
for name, pred in [
    ("删>=4板", lambda r: r["boards_T"] >= 4),
    ("删一字小额<2", lambda r: r["yizi"] and (r["amount_yi"] or 99) < 2),
    ("删 近板且(>=4板或额<2)", lambda r: r["open_pct_T1"]>=9 and (r["boards_T"]>=4 or (r["amount_yi"] or 99)<2)),
    ("删 中发酵近板 fb3-5 open>=9", lambda r: 3<=r["fb"]<=5 and r["open_pct_T1"]>=9),
]:
    left = [r for r in touch if not pred(r)]
    z = sum(1 for r in left if r["zhaban"])
    print(f"删后 {name}: 摸{len(left)} 炸{z} 炸板率{z/len(left):.1%}")
