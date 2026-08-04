# -*- coding: utf-8 -*-
"""用已落盘的原始数据反查字段假设是否成立。

要验证的假设：
  row[15] == 请求的连板高度 pid
  row[5]  == 主题材
  row[12] == 概念标签
  row[22] == 涨幅
  是否含 ST
  是否存在跨板重复代码
"""
import io
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
RAW = Path(r"D:\Ultra-Board\data\kaipanla\raw")

idx15_ok = idx15_bad = 0
bad_samples = []
len_dist = Counter()
st_hits = []
dup_days = []
pct_out_of_range = []

days = [d for d in sorted(RAW.iterdir()) if (d / "ladder.json").exists()]
print(f"检查 {len(days)} 天\n")

for d in days:
    doc = json.loads((d / "ladder.json").read_text(encoding="utf-8"))
    ladder = doc.get("ladder") or {}
    seen = {}
    for k, rows in ladder.items():
        pid = int(k)
        for row in rows:
            if not isinstance(row, list):
                continue
            len_dist[len(row)] += 1

            # 假设1: row[15] == pid
            if len(row) > 15:
                if row[15] == pid:
                    idx15_ok += 1
                else:
                    idx15_bad += 1
                    if len(bad_samples) < 8:
                        bad_samples.append((d.name, pid, row[0], row[1], row[15]))

            # ST 检查
            name = str(row[1])
            if "ST" in name.upper():
                st_hits.append((d.name, row[0], name, pid))

            # 跨板重复
            code = row[0]
            if code in seen and seen[code] != pid:
                dup_days.append((d.name, code, seen[code], pid))
            seen[code] = pid

            # 假设: row[22] 是涨幅，应在 4~31 之间
            if len(row) > 22 and isinstance(row[22], (int, float)):
                if not (3.5 <= row[22] <= 31):
                    pct_out_of_range.append((d.name, row[0], row[1], row[22]))

print("=== 假设1: row[15] == 连板高度 ===")
total = idx15_ok + idx15_bad
print(f"  一致 {idx15_ok} / {total}  不一致 {idx15_bad}")
for s in bad_samples:
    print(f"    反例: {s[0]} pid={s[1]} {s[2]} {s[3]} row15={s[4]}")

print("\n=== 原始行长度分布 ===")
for ln, c in sorted(len_dist.items()):
    print(f"  len={ln}: {c}")

print(f"\n=== ST 检查（应为 0）: {len(st_hits)} ===")
for s in st_hits[:10]:
    print(f"    {s}")

print(f"\n=== 跨板重复代码（应为 0）: {len(dup_days)} ===")
for s in dup_days[:10]:
    print(f"    {s}")

print(f"\n=== row[22] 疑似非涨幅: {len(pct_out_of_range)} ===")
for s in pct_out_of_range[:10]:
    print(f"    {s}")

# 抽一条完整样本，逐位打印
sample_day = days[-1]
doc = json.loads((sample_day / "ladder.json").read_text(encoding="utf-8"))
for k in sorted(doc.get("ladder", {}), key=lambda x: -int(x)):
    rows = doc["ladder"][k]
    if rows:
        print(f"\n=== 逐位样本 {sample_day.name} {k}板 ===")
        for i, v in enumerate(rows[0]):
            sv = str(v)
            print(f"  [{i:>2}] {sv[:60]}")
        break
