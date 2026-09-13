import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")


def load(d):
    return json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def blob(s):
    return (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")


d = "2024-10-24"
prev = "2024-10-23"
data = load(d)
prev_data = load(prev)

print(f"==== {d} count={data['count']} H={data['max_board']} ====")
print("主标签", ", ".join(f"{k}{v}" for k, v in Counter(s.get("theme") or "?" for s in data["stocks"]).most_common(12)))

print("\n一字或近一字 (09:25 且换手<=6.5):")
for s in sorted(data["stocks"], key=lambda x: -(x.get("boards") or 0)):
    if hhmm(s.get("first_limit_ts")) == "09:25" and (s.get("turnover_rate") or 99) <= 6.5:
        print(
            f"  {s['name']} {s['boards']}板 换手{s['turnover_rate']} "
            f"theme={s.get('theme')} tags={s.get('theme_tags_text')}"
        )

print("\n高度前10:")
for s in sorted(data["stocks"], key=lambda x: -(x.get("boards") or 0))[:10]:
    print(
        f"  {s['name']} {s['boards']}板 {hhmm(s.get('first_limit_ts'))} "
        f"换手{s['turnover_rate']} {s.get('theme')} / {s.get('theme_tags_text')}"
    )


def count_theme(data, key):
    main = sum(1 for s in data["stocks"] if (s.get("theme") or "") == key)
    attr = sum(1 for s in data["stocks"] if key in blob(s))
    return main, attr


print("\n关键池 23→24:")
for key in [
    "西部大开发",
    "基础建设",
    "并购重组",
    "通信",
    "算力",
    "低空经济",
    "芯片",
    "股权转让",
    "医药",
]:
    a, b = count_theme(prev_data, key)
    c, d = count_theme(data, key)
    print(f"  {key} 主{a}→{c} 属{b}→{d}")
