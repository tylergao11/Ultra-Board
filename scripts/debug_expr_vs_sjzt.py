# -*- coding: utf-8 -*-
"""对照 expression 分档合计 vs SJZT vs API，判断 SJZT 是否含北交所"""
import io, json, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
RAW = Path(r"D:\Ultra-Board\data\kaipanla\raw")

days = ["2025-10-09", "2025-11-05", "2026-01-06", "2026-03-03", "2026-07-03", "2026-08-03"]
print(f"{'日期':<12}{'SJZT':>5}{'expr合计':>8}{'一板':>5}{'二板':>5}{'三板':>5}{'高度板':>6}{'池子':>5}")
for day in days:
    d = RAW / day
    if not (d / "sentiment.json").exists():
        continue
    sent = json.loads((d / "sentiment.json").read_text(encoding="utf-8"))
    expr = json.loads((d / "expression.json").read_text(encoding="utf-8"))
    pool = json.loads((d / "zt_pool.json").read_text(encoding="utf-8"))
    info = expr.get("info") or []
    # info[0]一板 [1]二板 [2]三板 [3]高度板(家数不是高度)
    a, b, c, h = info[0], info[1], info[2], info[3]
    total = a + b + c + h
    sjzt = int(sent["info"]["SJZT"])
    print(f"{day:<12}{sjzt:>5}{total:>8}{a:>5}{b:>5}{c:>5}{h:>6}{pool['count']:>5}  "
          f"{'expr=SJZT' if total==sjzt else 'expr≠SJZT'}  "
          f"{'池=SJZT' if pool['count']==sjzt else '池≠SJZT'}")

print("""
说明: expression 的「高度板」是 4板及以上的合计家数。
若 expr合计 == SJZT，则 SJZT 口径 = 一板+二板+三板+高度板（开盘啦自己的梯队统计）。
""")
