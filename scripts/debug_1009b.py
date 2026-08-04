# -*- coding: utf-8 -*-
import io, json, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

pool = json.loads(Path(r"D:\Ultra-Board\data\kaipanla\raw\2025-10-09\zt_pool.json").read_text(encoding="utf-8"))

print("=== 首板里可疑票（北交所/特殊）===")
for s in pool["stocks"]:
    if s["boards"] != 1:
        continue
    code = s["code"]
    tag = []
    if code.startswith(("920", "8", "4")):
        tag.append("北交所?")
    if code.startswith("688"):
        tag.append("科创")
    if code.startswith(("300", "301")):
        tag.append("创业")
    if s["is_fanbao"]:
        tag.append("反包")
    if tag:
        print(f"  {code} {s['name']:<10} {s['theme']:<12} {tag}")

print("\n=== 所有北交所（8/4/92开头）===")
for s in pool["stocks"]:
    c = s["code"]
    if c.startswith(("920", "83", "87", "43")) or (c.startswith("8") and len(c)==6):
        print(f"  {s['boards']}板 {c} {s['name']} 题材={s['theme']} 反包={s['is_fanbao']}")

print("\n=== expression 一板77 vs 池子首板79，差额2，列出全部首板代码数 ===")
first = [s for s in pool["stocks"] if s["boards"] == 1]
print(f"首板数={len(first)}")
bse = [s for s in first if s["code"].startswith("920") or s["code"].startswith("8") and not s["code"].startswith(("60","00","30"))]
# simpler
bse = [s for s in first if s["code"].startswith("920")]
print(f"其中 920 北交所={len(bse)}")
for s in bse:
    print(f"  {s['code']} {s['name']}")
