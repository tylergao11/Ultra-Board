import json
from pathlib import Path
ROOT = Path("data/kaipanla/raw")
code = "001316"
for d in sorted(p.name for p in ROOT.iterdir() if (p/"zt_pool.json").exists()):
    if d < "2024-07-15" or d > "2024-08-06":
        continue
    data = json.loads((ROOT/d/"zt_pool.json").read_text(encoding="utf-8"))
    s = next((x for x in data["stocks"] if x["code"]==code), None)
    if not s:
        continue
    cap = s["raw"][13]
    print(d, f"{s['boards']}板 价{s['price']} 流通{cap/1e8:.2f}亿 换手{s['turnover_rate']}")
