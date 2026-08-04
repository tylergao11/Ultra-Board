# -*- coding: utf-8 -*-
"""验证 PidType 语义：5 是否为「5板及以上」；6+ 是否恒空"""
import io
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
RAW = Path(r"D:\Ultra-Board\data\kaipanla\raw")

print("=== 每个 pid 分组内 row[15] 的真实板数分布 ===")
per_pid = {}
for d in sorted(RAW.iterdir()):
    f = d / "ladder.json"
    if not f.exists():
        continue
    ladder = json.loads(f.read_text(encoding="utf-8")).get("ladder") or {}
    for k, rows in ladder.items():
        pid = int(k)
        c = per_pid.setdefault(pid, Counter())
        for row in rows:
            if isinstance(row, list) and len(row) > 15:
                c[row[15]] += 1

for pid in sorted(per_pid):
    dist = dict(sorted(per_pid[pid].items()))
    print(f"  PidType={pid}: row15分布={dist}")

print("\n=== 各日 pid=5 组内最高真实板数 vs 记录的 max_consecutive ===")
for d in sorted(RAW.iterdir()):
    f = d / "ladder.json"
    if not f.exists():
        continue
    doc = json.loads(f.read_text(encoding="utf-8"))
    ladder = doc.get("ladder") or {}
    top = 0
    for k, rows in ladder.items():
        for row in rows:
            if isinstance(row, list) and len(row) > 15 and isinstance(row[15], int):
                top = max(top, row[15])
    print(f"  {d.name}: 真实最高板={top}  记录max_consecutive={doc.get('max_consecutive')}")

print("\n=== row[18] 文字与 row[15] 是否一致 ===")
bad = 0
samples = []
for d in sorted(RAW.iterdir()):
    f = d / "ladder.json"
    if not f.exists():
        continue
    ladder = json.loads(f.read_text(encoding="utf-8")).get("ladder") or {}
    for k, rows in ladder.items():
        for row in rows:
            if isinstance(row, list) and len(row) > 18:
                txt = str(row[18])
                n = row[15]
                if txt and txt != "":
                    if f"{n}连板" != txt and len(samples) < 12:
                        samples.append((d.name, row[0], row[1], n, txt))
                        bad += 1
print(f"  不一致 {bad} 条")
for s in samples:
    print(f"    {s}")
