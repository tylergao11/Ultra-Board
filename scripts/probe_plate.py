# -*- coding: utf-8 -*-
"""摸清 GetPlateInfo / 涨停原因板块 正确参数"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ultraboard.kaipanla.client import HIS_URL, SECTOR_URL, KaipanlaClient, ok

DATA = ROOT / "data" / "kaipanla"
DAY = "2026-08-03"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    c = KaipanlaClient(DATA)

    print("### DailyLimitPerformance p2 全文结构 ###")
    j = c.daily_limit_performance(DAY, 2)
    print(json.dumps(j, ensure_ascii=False)[:1500])

    print("\n### GetPlateInfo 变体 ###")
    trials = [
        ("apphwhq DailyLimitResumption", SECTOR_URL,
         {"a": "GetPlateInfo_w38", "st": "100", "c": "DailyLimitResumption", "Index": "0"}),
        ("apphis DailyLimitResumption", HIS_URL,
         {"a": "GetPlateInfo_w38", "st": "100", "c": "DailyLimitResumption", "Index": "0"}),
        ("apphwhq HisDailyLimitResumption", SECTOR_URL,
         {"a": "GetPlateInfo_w38", "st": "100", "c": "HisDailyLimitResumption", "Index": "0"}),
        ("apphis HisDailyLimitResumption", HIS_URL,
         {"a": "GetPlateInfo_w38", "st": "100", "c": "HisDailyLimitResumption", "Index": "0"}),
        ("apphwhq HomeDingPan", SECTOR_URL,
         {"a": "GetPlateInfo_w38", "st": "100", "c": "HomeDingPan", "Index": "0"}),
        ("apphis GetPlateInfo_w8", HIS_URL,
         {"a": "GetPlateInfo_w8", "st": "30", "c": "HisHomeDingPan", "Index": "0", "Order": "1"}),
        ("apphwhq ZhiShuStockList", SECTOR_URL,
         {"a": "ZhiShuStockList_W8", "st": "30", "c": "ZhiShuRanking", "Index": "0",
          "Order": "1", "Type": "6", "PidType": "1"}),
        ("apphis HisDaBanList t6", HIS_URL,
         {"Order": "1", "a": "HisDaBanList", "st": "100", "c": "HisHomeDingPan",
          "Index": "0", "Is_st": "1", "PidType": "1", "Type": "6",
          "FilterMotherboard": "0", "Filter": "0", "FilterTIB": "0", "FilterGem": "0"}),
        ("apphis HisDaBanList t5", HIS_URL,
         {"Order": "1", "a": "HisDaBanList", "st": "100", "c": "HisHomeDingPan",
          "Index": "0", "Is_st": "1", "PidType": "1", "Type": "5",
          "FilterMotherboard": "0", "Filter": "0", "FilterTIB": "0", "FilterGem": "0"}),
        ("apphis HisDaBanList t0", HIS_URL,
         {"Order": "1", "a": "HisDaBanList", "st": "100", "c": "HisHomeDingPan",
          "Index": "0", "Is_st": "1", "PidType": "1", "Type": "0",
          "FilterMotherboard": "0", "Filter": "0", "FilterTIB": "0", "FilterGem": "0"}),
    ]
    for tag, url, extra in trials:
        body = c.post(url, extra, DAY)
        err = body.get("errcode")
        keys = list(body.keys())[:12]
        lst = body.get("list") or body.get("info") or []
        n = len(lst) if isinstance(lst, list) else 0
        print(f"\n[{err}] {tag}  n={n} keys={keys}")
        if ok(body):
            print(json.dumps(body, ensure_ascii=False)[:500])


if __name__ == "__main__":
    raise SystemExit(main())
