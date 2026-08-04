import json
from pathlib import Path
import sys
sys.path.insert(0, "scripts/_scratch")
import backtest_main_ladder as bt

cases = [
    ("2026-07-17", "浙江美大"),
    ("2026-03-26", "新能泰山"),
    ("2026-04-08", "汇源通信"),
]

raw = Path("data/kaipanla/raw")
for d, name in cases:
    print("=" * 70)
    print(d, name)
    p = raw / d / "zt_pool.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    stocks = data if isinstance(data, list) else data.get("list") or data.get("data") or []
    # find stock
    hit = None
    for s in stocks:
        if isinstance(s, dict) and s.get("name") == name:
            hit = s
            break
    if not hit:
        # maybe nested
        def walk(o, depth=0):
            if isinstance(o, dict):
                if o.get("name") == name:
                    return o
                for v in o.values():
                    r = walk(v, depth+1)
                    if r: return r
            elif isinstance(o, list):
                for i in o:
                    r = walk(i, depth+1)
                    if r: return r
            return None
        hit = walk(data)
    if not hit:
        print("  NOT FOUND in raw")
        continue
    # print key fields related to yizi / seal
    keys = sorted(hit.keys())
    print("  keys sample:", [k for k in keys if any(x in k.lower() for x in ["r", "feng", "yi", "first", "limit", "open", "time", "board", "theme", "stat", "type"])][:40])
    interesting = {}
    for k, v in hit.items():
        kl = str(k).lower()
        if any(x in kl for x in ["r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15", "r16", "r17", "r18", "r19", "r20", "first", "feng", "seal", "open", "board", "theme", "name", "code", "stat", "limit", "yi", "one", "time", "amt", "money", "amount", "change"]):
            interesting[k] = v
    # dump compact
    for k in sorted(interesting.keys(), key=str):
        print(f"  {k}: {interesting[k]}")
    print("  is_yizi(bt)=", bt.is_yizi(hit) if "boards" in hit or True else "?")
    # normalize via pool load
    for s in bt._POOLS_BY_DAY.get(d) or []:
        if s.get("name") == name:
            print("  pool boards", s.get("boards"), "theme", s.get("theme"))
            print("  is_yizi", bt.is_yizi(s), "is_gonggao", bt.is_gonggao(s,d), "is_natural", bt.is_natural(s,d), "is_reorg", bt.is_reorg(s))
            # show fields used by is_yizi
            for k in ["first_limit_time", "first_feng", "r17", "r18", "open_pct", "status", "limit_up_type", "is_yizi", "yizi", "fengdan"]:
                if k in s:
                    print(f"   field {k}={s.get(k)}")
            print("  all short fields:")
            for k,v in sorted(s.items()):
                if not isinstance(v, (list, dict)):
                    print(f"   {k}={v}")
