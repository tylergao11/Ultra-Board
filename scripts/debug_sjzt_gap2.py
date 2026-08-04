# -*- coding: utf-8 -*-
"""深挖缺口：BSE口径 vs 真缺票；600989 是什么"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(r"D:\Ultra-Board")
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from ultraboard.kaipanla.client import KaipanlaClient, ok
from ultraboard.kaipanla.backfill import is_bse, MAX_PID, _rows

DATA = ROOT / "data" / "kaipanla"
RAW = DATA / "raw"


def analyze_day(c: KaipanlaClient, day: str):
    sent = json.loads((RAW / day / "sentiment.json").read_text(encoding="utf-8"))
    pool = json.loads((RAW / day / "zt_pool.json").read_text(encoding="utf-8"))
    sjzt = int(sent["info"]["SJZT"])
    zt = int(sent["info"]["ZT"])
    stzt = int(sent["info"]["STZT"])

    bse_codes = []
    hs_codes = []
    for pid in range(1, MAX_PID + 1):
        body = c.daily_limit_performance(day, pid)
        for row in _rows(body) if ok(body) else []:
            if not isinstance(row, list) or not row:
                continue
            code, name = str(row[0]), str(row[1])
            boards = row[15] if len(row) > 15 else "?"
            if is_bse(code):
                bse_codes.append((code, name, boards, pid))
            else:
                hs_codes.append((code, name, boards, pid))

    print(f"\n{'='*70}")
    print(f"{day}")
    print(f"  ZT={zt} SJZT={sjzt} STZT={stzt}  (ZT应≈SJZT+STZT={sjzt+stzt})")
    print(f"  API原始: 沪深={len(hs_codes)} 北交所={len(bse_codes)} 合计={len(hs_codes)+len(bse_codes)}")
    print(f"  我们池子={pool['count']}")
    print(f"  若SJZT含北交所: 期望池子={sjzt}-北交={sjzt-len(bse_codes)}  实际={len(hs_codes)}  差={sjzt-len(bse_codes)-len(hs_codes)}")
    print(f"  若SJZT不含北交所: 期望={sjzt}  实际={len(hs_codes)}  差={sjzt-len(hs_codes)}")
    if bse_codes:
        print("  北交所明细:")
        for x in bse_codes:
            print(f"    {x[0]} {x[1]} 板数={x[2]} pid={x[3]}")

    # 板块有池子无
    sec = json.loads((RAW / day / "sector_ladder.json").read_text(encoding="utf-8"))
    missing = []
    pool_set = {s["code"] for s in pool["stocks"]}
    for s in sec.get("sectors") or []:
        for stocks in (s.get("tiers") or {}).values():
            for x in stocks:
                if x["code"] not in pool_set and not is_bse(x["code"]):
                    missing.append((x["code"], x["name"], s["name"], "tier"))
        for x in s.get("fanbao") or []:
            if x["code"] not in pool_set and not is_bse(x["code"]):
                missing.append((x["code"], x["name"], s["name"], f"fanbao:{x.get('tips')}"))
    if missing:
        print("  板块有、池子无:")
        for m in missing:
            print(f"    {m}")


def lookup_600989(c: KaipanlaClient):
    day = "2026-07-03"
    print(f"\n{'='*70}\n查 600989 @ {day}")
    for pid in range(1, 6):
        body = c.daily_limit_performance(day, pid)
        for row in _rows(body) if ok(body) else []:
            if isinstance(row, list) and str(row[0]) == "600989":
                print(f"  在 pid={pid}: {row[:6]} ... boards={row[15]} desc={row[18]!r}")
                return
    print("  不在 DailyLimitPerformance 任何 pid 里")

    # 板块信息
    sec = json.loads((RAW / day / "sector_ladder.json").read_text(encoding="utf-8"))
    for s in sec.get("sectors") or []:
        for t, stocks in (s.get("tiers") or {}).items():
            for x in stocks:
                if x["code"] == "600989":
                    print(f"  在板块梯队: [{s['name']}] {t}板 {x}")
        for x in s.get("fanbao") or []:
            if x["code"] == "600989":
                print(f"  在反包: [{s['name']}] {x}")

    # HisDaBanList 试试
    from ultraboard.kaipanla.client import HIS_URL
    for typ in range(0, 9):
        body = c.post(HIS_URL, {
            "Order": "1", "a": "HisDaBanList", "st": "300", "c": "HisHomeDingPan",
            "Index": "0", "Is_st": "1", "PidType": "1", "Type": str(typ),
            "FilterMotherboard": "0", "Filter": "0", "FilterTIB": "0", "FilterGem": "0",
        }, day)
        lst = body.get("list") or []
        for row in lst:
            if isinstance(row, list) and str(row[0]) == "600989":
                print(f"  HisDaBanList Type={typ}: {row[:12]}")


def main():
    c = KaipanlaClient(DATA, 0.5, 1.0)
    for day in ["2025-11-05", "2026-01-06", "2026-07-03", "2026-03-03"]:
        analyze_day(c, day)
    lookup_600989(c)

    # 统计：有多少 mismatch 的 gap 恰好等于当天北交所数量
    print(f"\n{'='*70}\n统计：缺口是否等于北交所数量？")
    c2 = KaipanlaClient(DATA, 0.3, 0.6)
    match_bse = other = 0
    # 只抽 mismatches 里的若干天快速看（用已落盘：重拉太慢）
    # 改为：对所有 MISMATCH 日，用「池子+猜测」——我们没存北交所。
    # 所以对 samples 结论推广即可。
    print("  见上面样本分析。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
