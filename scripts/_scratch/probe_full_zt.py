# -*- coding: utf-8 -*-
"""找开盘啦「完整涨停池」接口，对照 ZT=83 那天(2025-11-05)"""
from __future__ import annotations

import io, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from ultraboard.kaipanla.client import HIS_URL, SECTOR_URL, KaipanlaClient, ok

DAY = "2025-11-05"
DATA = ROOT / "data" / "kaipanla"
TARGET_ZT = 83  # 该日 HisZhangFuDetail 的 ZT


def main():
    c = KaipanlaClient(DATA, 1.0, 1.2)
    print(f"目标日 {DAY} 官方统计 ZT={TARGET_ZT}\n")

    # 1) 现有 ladder 覆盖
    L = json.loads((DATA / "raw" / DAY / "ladder.json").read_text(encoding="utf-8"))
    codes = set()
    for k, rows in (L.get("ladder") or {}).items():
        for r in rows:
            if isinstance(r, list) and r:
                codes.add(r[0])
    print(f"[现有 ladder] 去重代码数={len(codes)}")

    # 2) HisDaBanList 各 Type / PidType
    print("\n### HisDaBanList 矩阵 ###")
    for typ in range(0, 9):
        for pid in (0, 1, 2):
            body = c.post(
                HIS_URL,
                {
                    "Order": "1",
                    "a": "HisDaBanList",
                    "st": "300",
                    "c": "HisHomeDingPan",
                    "Index": "0",
                    "Is_st": "1",
                    "PidType": str(pid),
                    "Type": str(typ),
                    "FilterMotherboard": "0",
                    "Filter": "0",
                    "FilterTIB": "0",
                    "FilterGem": "0",
                },
                DAY,
            )
            lst = body.get("list") or []
            day_field = body.get("day")
            print(
                f"  Type={typ} PidType={pid}: err={body.get('errcode')} "
                f"n={len(lst)} day={day_field}"
            )
            if ok(body) and lst and isinstance(lst[0], list):
                print(f"    sample: {lst[0][0]} {lst[0][1]} theme={lst[0][11] if len(lst[0])>11 else '?'}")

    # 3) DailyLimitPerformance PidType=0 ?
    print("\n### DailyLimitPerformance PidType=0 ###")
    body = c.daily_limit_performance(DAY, 0)
    info = body.get("info") or []
    n = len(info[0]) if info and isinstance(info[0], list) else 0
    print(f"  err={body.get('errcode')} info_len={len(info)} stocks0={n}")

    # 4) 分页拉 HisDaBanList Type=6 Index
    print("\n### HisDaBanList Type=6 分页 ###")
    for idx in (0, 1, 2):
        body = c.post(
            HIS_URL,
            {
                "Order": "1",
                "a": "HisDaBanList",
                "st": "100",
                "c": "HisHomeDingPan",
                "Index": str(idx),
                "Is_st": "1",
                "PidType": "1",
                "Type": "6",
                "FilterMotherboard": "0",
                "Filter": "0",
                "FilterTIB": "0",
                "FilterGem": "0",
            },
            DAY,
        )
        lst = body.get("list") or []
        print(f"  Index={idx}: n={len(lst)} day={body.get('day')} err={body.get('errcode')}")


if __name__ == "__main__":
    raise SystemExit(main())
