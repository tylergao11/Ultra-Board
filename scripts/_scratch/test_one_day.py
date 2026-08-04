# -*- coding: utf-8 -*-
"""单日验证：先试今天，拿不到就退回昨天。跑完做完整性检查。"""
from __future__ import annotations

import io
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from ultraboard.kaipanla.backfill import DATA_DIR, day_dir, pull_one_day
from ultraboard.kaipanla.client import KaipanlaClient


def report(d: date) -> None:
    dd = day_dir(d)
    pool = json.loads((dd / "zt_pool.json").read_text(encoding="utf-8"))
    sec = json.loads((dd / "sector_ladder.json").read_text(encoding="utf-8"))
    sent = json.loads((dd / "sentiment.json").read_text(encoding="utf-8"))
    info = sent.get("info") or {}

    print("\n" + "=" * 70)
    print(f"日期 {pool['date']}")
    print("=" * 70)
    print(f"  官方 ZT={info.get('ZT')}  SJZT={info.get('SJZT')}  STZT={info.get('STZT')}")
    print(f"  拉到涨停池 {pool['count']} 只  (应等于 SJZT)")
    print(f"  最高板 {pool['max_board']}  反包 {pool['fanbao_count']} 只")
    print(f"  分布 {dict(sorted(pool['board_counts'].items(), key=lambda x: -int(x[0])))}")
    print(f"  情绪判语 {info.get('sign')}")

    print("\n  --- 2板及以上（连板梯队）---")
    for s in pool["stocks"]:
        if s["boards"] >= 2:
            flag = " [反包]" if s["is_fanbao"] else ""
            print(f"    {s['boards']}板  {s['code']} {s['name']:<8} "
                  f"{s['theme']:<12} {s['concepts']}{flag}")

    fb = [s for s in pool["stocks"] if s["is_fanbao"]]
    print(f"\n  --- 反包板 {len(fb)} 只（按真实连板归队，未抬高）---")
    for s in fb:
        print(f"    真实{s['boards']}板  {s['code']} {s['name']:<8} "
              f"描述={s['boards_desc']!r} 题材={s['theme']}")

    print(f"\n  --- 板块梯队 {len(sec['sectors'])} 个 ---")
    for x in sec["sectors"]:
        tiers = {k: [i["name"] for i in v] for k, v in sorted(
            x["tiers"].items(), key=lambda kv: -int(kv[0]))}
        print(f"    [{x['name']}] 涨停{x['count']}只")
        for k, names in tiers.items():
            print(f"        {k}板: {names}")
        if x["fanbao"]:
            print(f"        反包: {[(i['name'], i['tips']) for i in x['fanbao']]}")

    # 完整性检查
    print("\n  --- 完整性检查 ---")
    codes = [s["code"] for s in pool["stocks"]]
    problems = []
    if len(codes) != len(set(codes)):
        problems.append("存在重复代码")
    if pool["count"] != pool["sjzt"]:
        problems.append(f"数量不符 {pool['count']} vs SJZT {pool['sjzt']}")
    for s in pool["stocks"]:
        if not isinstance(s["boards"], int) or s["boards"] < 1:
            problems.append(f"{s['code']} boards 非法")
        if "ST" in s["name"].upper():
            problems.append(f"{s['code']} {s['name']} 疑似 ST")
    print("    " + ("全部通过" if not problems else "；".join(problems)))
    print(f"    _DONE 存在: {(dd / '_DONE').exists()}")


def main() -> int:
    client = KaipanlaClient(DATA_DIR, 1.0, 2.0)
    non_trading: set[str] = set()

    for d in (date(2026, 8, 4), date(2026, 8, 3)):
        print(f"\n>>> 尝试 {d.isoformat()}", flush=True)
        status, msg = pull_one_day(client, d, non_trading)
        print(f"    status={status} msg={msg}")
        if status in ("ok", "mismatch"):
            report(d)
            return 0
        if status == "skip":
            print("    未入库（18:00 前）或非交易日，退回前一天")
            continue
        print("    失败，停止")
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
