# -*- coding: utf-8 -*-
"""追踪反包板的真实历史轨迹，验证 Tips 能否推出反包前梯队。

目标票（2025-11-05 的反包板）：
  600089 特变电工  Tips=3天2板
  600759 洲际油气  Tips=3天2板
  002163 海南发展  Tips=6天3板

做法：逐日拉 pid=1..5 涨停池，看这几只在每天的真实板数；
不在池中 = 当日未涨停（断板）。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from ultraboard.kaipanla.client import KaipanlaClient, ok

DATA = ROOT / "data" / "kaipanla"
DAYS = [
    "2025-10-27", "2025-10-28", "2025-10-29", "2025-10-30", "2025-10-31",
    "2025-11-03", "2025-11-04", "2025-11-05",
]
TARGETS = {"600089": "特变电工", "600759": "洲际油气", "002163": "海南发展"}


def rows_of(body):
    info = body.get("info") or []
    if not info:
        return []
    return info[0] if isinstance(info[0], list) else []


def main():
    c = KaipanlaClient(DATA, 1.0, 1.5)
    history = {code: {} for code in TARGETS}

    for day in DAYS:
        found = {}
        for pid in range(1, 6):
            body = c.daily_limit_performance(day, pid)
            if not ok(body):
                continue
            for r in rows_of(body):
                if isinstance(r, list) and len(r) > 18 and str(r[0]) in TARGETS:
                    found[str(r[0])] = (r[15], r[18])
        for code in TARGETS:
            history[code][day] = found.get(code)
        print(f"{day} 扫完: {[(k, v) for k, v in found.items()]}", flush=True)

    print("\n" + "=" * 72)
    for code, name in TARGETS.items():
        print(f"\n### {code} {name} ###")
        streak_before = []
        for day in DAYS:
            v = history[code][day]
            if v is None:
                print(f"  {day}  —— 未涨停（断板）")
            else:
                boards, desc = v
                print(f"  {day}  涨停 板数={boards} 描述={desc!r}")
                streak_before.append((day, boards))
        # 反包前最后一次涨停时的板数
        prev = [x for x in streak_before if x[0] != DAYS[-1]]
        if prev:
            print(f"  => 反包前最后一次涨停: {prev[-1][0]} 板数={prev[-1][1]}")
        else:
            print("  => 区间内反包前无涨停记录，需再往前回溯")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
