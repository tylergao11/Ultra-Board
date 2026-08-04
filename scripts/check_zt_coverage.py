# -*- coding: utf-8 -*-
import io, sys, json
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
raw = Path(r"D:\Ultra-Board\data\kaipanla\raw")
print(f"{'日期':<12}{'ZT':>6}{'梯队合计':>8}{'首板':>6}{'2板+':>6}{'缺口':>6}")
for d in sorted(raw.iterdir()):
    done = d / "_DONE"
    ladder = d / "ladder.json"
    zf = d / "HisZhangFuDetail.json"
    if not done.exists() or not ladder.exists():
        continue
    z = json.loads(zf.read_text(encoding="utf-8"))
    zt = (z.get("info") or {}).get("ZT")
    try:
        zt = int(zt)
    except Exception:
        pass
    L = json.loads(ladder.read_text(encoding="utf-8")).get("ladder") or {}
    n1 = len(L.get("1") or [])
    n2 = sum(len(v) for k, v in L.items() if k != "1")
    total = n1 + n2
    gap = (zt - total) if isinstance(zt, int) else "?"
    print(f"{d.name:<12}{zt!s:>6}{total:>8}{n1:>6}{n2:>6}{gap!s:>6}")
