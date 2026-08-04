# -*- coding: utf-8 -*-
"""反包板到底落在哪个梯队？

做法：拉 2025-11-05 的 pid=1..5 涨停池，找出 GetYTFP_BKHX 标记为
TDType=0（反包板）的那几只，看它们在涨停池里的 row[15]（真实板数）
和 row[18]（连板描述）。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from ultraboard.kaipanla.client import KaipanlaClient, ok

DATA = ROOT / "data" / "kaipanla"
DAY = "2025-11-05"


def stock_rows(body):
    info = body.get("info") or []
    if not info:
        return []
    return info[0] if isinstance(info[0], list) else []


def main():
    c = KaipanlaClient(DATA, 1.0, 1.5)

    # 1) 板块梯队 + 反包板
    sec = c.sector_ladder(DAY)
    if not ok(sec):
        print("sector_ladder failed", sec)
        return 1
    fanbao = {}
    tier_of = {}
    for s in sec.get("List") or []:
        for g in s.get("TD") or []:
            t = str(g.get("TDType"))
            for st in g.get("Stock") or []:
                code = st.get("StockID")
                if t == "0":
                    fanbao[code] = (s.get("ZSName"), st.get("StockName"), st.get("Tips"))
                else:
                    tier_of[code] = (t, s.get("ZSName"), st.get("StockName"))
    print(f"反包板 {len(fanbao)} 只: {[(k, v[1], v[2]) for k, v in fanbao.items()]}")

    # 2) 涨停池 pid=1..5
    pool = {}
    for pid in range(1, 6):
        body = c.daily_limit_performance(DAY, pid)
        rows = stock_rows(body) if ok(body) else []
        print(f"  pid={pid}: {len(rows)} 只")
        for r in rows:
            if isinstance(r, list) and len(r) > 18:
                pool[str(r[0])] = {"pid": pid, "row15": r[15], "row18": r[18],
                                   "name": r[1], "theme": r[5]}

    print(f"\n涨停池合计 {len(pool)} 只")

    print("\n=== 反包板在涨停池里的样子 ===")
    for code, (sector, name, tips) in fanbao.items():
        p = pool.get(str(code))
        if p:
            print(f"  {code} {name} [{sector}] Tips={tips!r}")
            print(f"      -> pid={p['pid']} row15(真实板数)={p['row15']} row18(描述)={p['row18']!r}")
        else:
            print(f"  {code} {name} [{sector}] Tips={tips!r}  -> 不在涨停池！")

    print("\n=== row18 非空的所有票（看描述格式） ===")
    n = 0
    for code, p in pool.items():
        if p["row18"]:
            print(f"  {code} {p['name']:<8} pid={p['pid']} row15={p['row15']} row18={p['row18']!r}")
            n += 1
            if n >= 25:
                break

    print("\n=== row15 与 pid 不一致的票（验证 pid5=5板及以上） ===")
    for code, p in pool.items():
        if p["row15"] != p["pid"]:
            print(f"  {code} {p['name']:<8} pid={p['pid']} row15={p['row15']} row18={p['row18']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
