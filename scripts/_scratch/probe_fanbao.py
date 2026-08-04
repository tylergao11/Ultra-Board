# -*- coding: utf-8 -*-
"""探 GetYTFP_BKHX：板块连板梯队 + 反包板(TDType=0)。历史参数是 Date 不是 Day。"""
from __future__ import annotations

import io
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from ultraboard.kaipanla.client import HIS_URL, SECTOR_URL, KaipanlaClient, ok

DATA = ROOT / "data" / "kaipanla"
DAY = "2025-11-05"


def main():
    c = KaipanlaClient(DATA, 1.0, 1.5)

    trials = [
        ("apphis Date", HIS_URL, {"a": "GetYTFP_BKHX", "c": "FuPanLa", "Date": DAY}),
        ("apphwhq Date", SECTOR_URL, {"a": "GetYTFP_BKHX", "c": "FuPanLa", "Date": DAY}),
        ("apphis Day", HIS_URL, {"a": "GetYTFP_BKHX", "c": "FuPanLa", "Day": DAY}),
    ]
    good = None
    for tag, url, extra in trials:
        body = c.post(url, extra)  # 不自动加 Day
        keys = [k for k in body.keys() if k != "ttag"]
        n = len(body.get("List") or [])
        print(f"[{body.get('errcode')}] {tag}: keys={keys} List={n} Date={body.get('Date')}")
        if ok(body) and n:
            good = body
            print(f"    -> 命中，用 {tag}")
            break

    if not good:
        print("未拿到 List，停")
        return 1

    tdtypes = Counter()
    fanbao = []
    sectors = good.get("List") or []
    for sec in sectors:
        for g in sec.get("TD") or []:
            t = str(g.get("TDType"))
            stocks = g.get("Stock") or []
            tdtypes[t] += len(stocks)
            if t == "0":
                for s in stocks:
                    fanbao.append((sec.get("ZSName"), s.get("StockID"), s.get("StockName"), s.get("Tips")))

    print(f"\n板块数={len(sectors)}")
    print(f"TDType 分布(股票数): {dict(sorted(tdtypes.items(), key=lambda x: x[0]))}")
    print("  0=反包板 1=首板 2=2连板 ... 9=打开高度标注")

    print(f"\n=== 反包板 {len(fanbao)} 只 ===")
    for f in fanbao[:20]:
        print(f"  [{f[0]}] {f[1]} {f[2]}  Tips={f[3]}")

    sec0 = sectors[0]
    print(f"\n=== 板块样本: {sec0.get('ZSName')} ({sec0.get('ZSCode')}) Count={sec0.get('Count')} ===")
    for g in sec0.get("TD") or []:
        names = [s.get("StockName") for s in (g.get("Stock") or [])]
        print(f"  TDType={g.get('TDType')}: {names}")
    print("\n股票字段样例:")
    for g in sec0.get("TD") or []:
        if g.get("Stock"):
            print(" ", json.dumps(g["Stock"][0], ensure_ascii=False))
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
