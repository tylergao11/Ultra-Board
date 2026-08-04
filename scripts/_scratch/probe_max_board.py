# -*- coding: utf-8 -*-
"""从已落盘数据核对：ZhangTingExpression 哪一位 = 日内最高板"""
import io, sys, json
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
raw = (Path(__file__).resolve().parents[2] / "data" / "kaipanla" / "raw")

print(f"{'日期':<12}{'ladder最高':>10}{'expr全文'}")
for d in sorted(raw.iterdir()):
    zt = d / "ZhangTingExpression.json"
    lad = d / "ladder.json"
    if not (d / "_DONE").exists() or not zt.exists() or not lad.exists():
        continue
    expr = json.loads(zt.read_text(encoding="utf-8")).get("info")
    L = json.loads(lad.read_text(encoding="utf-8"))
    mx = L.get("max_consecutive")
    print(f"{d.name:<12}{mx!s:>10}  {expr}")
