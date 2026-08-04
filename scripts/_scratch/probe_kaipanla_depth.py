# -*- coding: utf-8 -*-
"""探开盘啦回溯深度 + 核心接口可用性"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ultraboard.kaipanla.client import KaipanlaClient, ok

DATA = ROOT / "data" / "kaipanla"


def show(tag, body):
    err = body.get("errcode")
    keys = list(body.keys())[:10]
    n = 0
    if isinstance(body.get("list"), list):
        n = len(body["list"])
    elif isinstance(body.get("info"), list):
        n = len(body["info"])
    elif isinstance(body.get("info"), dict):
        n = body["info"].get("ZT", "?")
    print(f"  [{err}] {tag:<40} keys={keys} n={n}")
    if ok(body) and isinstance(body.get("list"), list) and body["list"]:
        first = body["list"][0]
        if isinstance(first, dict):
            print(f"       sample: {first.get('ZSName')} stocks={first.get('num')} code={first.get('ZSCode')}")
            sl = first.get("StockList") or []
            if sl and isinstance(sl[0], list) and len(sl[0]) > 16:
                s = sl[0]
                print(f"       stock0: {s[0]} {s[1]} 题材/原因位={s[16] if len(s)>16 else '?'}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    c = KaipanlaClient(DATA, interval_min=1.0, interval_max=2.0)
    print("DeviceID:", c.device_id)

    dates = [
        "2025-10-09",  # 国庆后首个交易日附近
        "2025-10-10",
        "2025-11-03",
        "2026-01-16",
        "2026-04-01",
        "2026-08-01",
        "2026-08-03",
        "2026-08-04",  # 今天，可能 18:00 前未入库
    ]
    for day in dates:
        print(f"\n=== {day} ===")
        show("HisZhangFuDetail", c.his_zhangfu(day))
        show("ZhangTingExpression", c.zhangting_expression(day))
        show("GetPlateInfo_w38", c.plate_info(day, 0))
        show("DailyLimitPerformance p2", c.daily_limit_performance(day, 2))
        show("DailyLimitPerformance p1", c.daily_limit_performance(day, 1))


if __name__ == "__main__":
    raise SystemExit(main())
