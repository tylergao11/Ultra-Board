# -*- coding: utf-8 -*-
"""查 SJZT 缺口：少的票是什么？是否停牌？"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from ultraboard.kaipanla.client import HIS_URL, KaipanlaClient, ok
from ultraboard.kaipanla.backfill import is_bse, MAX_PID, _rows, parse_stock

RAW = ROOT / "data" / "kaipanla" / "raw"
DATA = ROOT / "data" / "kaipanla"

# 抽几个缺口日：差1、差2、差3、差6
SAMPLES = ["2025-11-05", "2026-01-06", "2026-07-03", "2026-03-03"]


def load_pool_codes(day: str) -> set[str]:
    p = RAW / day / "zt_pool.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    return {s["code"] for s in doc["stocks"]}, doc


def sector_codes(day: str) -> tuple[set[str], set[str]]:
    """板块梯队正常票 + 反包票（已滤北交所）"""
    p = RAW / day / "sector_ladder.json"
    if not p.exists():
        return set(), set()
    doc = json.loads(p.read_text(encoding="utf-8"))
    normal, fanbao = set(), set()
    for s in doc.get("sectors") or []:
        for stocks in (s.get("tiers") or {}).values():
            for x in stocks:
                c = x["code"]
                if c and not is_bse(c):
                    normal.add(c)
        for x in s.get("fanbao") or []:
            c = x["code"]
            if c and not is_bse(c):
                fanbao.add(c)
    return normal, fanbao


def main():
    c = KaipanlaClient(DATA, 0.5, 1.0)

    for day in SAMPLES:
        print("=" * 72)
        pool_codes, pool = load_pool_codes(day)
        sent = json.loads((RAW / day / "sentiment.json").read_text(encoding="utf-8"))
        sjzt = int(sent["info"]["SJZT"])
        gap = sjzt - len(pool_codes)
        print(f"{day}  池子={len(pool_codes)}  SJZT={sjzt}  差={gap}")
        print(f"  分布={pool.get('board_counts')} 最高={pool.get('max_board')}")

        # 1) 板块梯队里有、涨停池没有
        normal, fanbao = sector_codes(day)
        in_sector_not_pool = (normal | fanbao) - pool_codes
        print(f"  板块梯队有、池子无: {len(in_sector_not_pool)} {sorted(in_sector_not_pool)}")

        # 2) 重拉 pid=1..5，看原始行数 vs 过滤后
        raw_n = kept_n = bse_n = parse_fail = 0
        fail_samples = []
        all_raw_codes = set()
        for pid in range(1, MAX_PID + 1):
            body = c.daily_limit_performance(day, pid)
            rows = _rows(body) if ok(body) else []
            for row in rows:
                raw_n += 1
                if isinstance(row, list) and row:
                    all_raw_codes.add(str(row[0]))
                item, err = parse_stock(row, pid)
                if item is None and err is None:
                    bse_n += 1
                    continue
                if err:
                    parse_fail += 1
                    if len(fail_samples) < 8:
                        code = row[0] if isinstance(row, list) else "?"
                        name = row[1] if isinstance(row, list) and len(row) > 1 else "?"
                        boards = row[15] if isinstance(row, list) and len(row) > 15 else "?"
                        fail_samples.append((pid, code, name, boards, err))
                    continue
                kept_n += 1
        print(f"  重拉原始={raw_n} 北交所滤掉={bse_n} 解析失败={parse_fail} 保留={kept_n}")
        for fs in fail_samples:
            print(f"    解析失败: pid={fs[0]} {fs[1]} {fs[2]} boards={fs[3]} | {fs[4]}")

        # 3) 对照 akshare（若有）
        try:
            import akshare as ak
            df = ak.stock_zt_pool_em(date=day.replace("-", ""))
            if df is None or len(df) == 0:
                print("  akshare 空")
            else:
                # 去掉 ST、北交所
                ak_df = df.copy()
                ak_df = ak_df[~ak_df["名称"].astype(str).str.contains("ST", case=False, na=False)]
                ak_df = ak_df[~ak_df["代码"].astype(str).map(is_bse)]
                ak_codes = set(ak_df["代码"].astype(str))
                only_ak = ak_codes - pool_codes
                only_pool = pool_codes - ak_codes
                print(f"  akshare非ST非北交={len(ak_codes)}  仅ak={len(only_ak)} 仅池={len(only_pool)}")
                if only_ak:
                    sub = ak_df[ak_df["代码"].astype(str).isin(only_ak)][
                        ["代码", "名称", "连板数", "首次封板时间", "所属行业"]
                    ]
                    print("  --- 仅 akshare 有（我们缺的）---")
                    print(sub.to_string(index=False))
        except Exception as e:
            print(f"  akshare FAIL: {type(e).__name__}: {e}")

        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
