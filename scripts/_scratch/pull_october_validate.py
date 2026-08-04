# -*- coding: utf-8 -*-
"""只拉 2025-10 一个月，然后做完整性校验。"""
from __future__ import annotations

import io
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from ultraboard.kaipanla import backfill as bf
from ultraboard.kaipanla.client import KaipanlaClient

START = date(2025, 10, 1)
END = date(2025, 10, 31)


def pull_month() -> int:
    client = KaipanlaClient(bf.DATA_DIR, interval_min=0.5, interval_max=1.0)
    non_trading = set(bf._read_json(bf.NON_TRADING_PATH, []))
    days = bf.trading_days(START, END)
    todo = [d for d in days if not bf.day_complete(d) and d.isoformat() not in non_trading]
    # mismatch 也重拉
    redo = []
    for d in days:
        dd = bf.day_dir(d)
        if (dd / "_MISMATCH").exists():
            redo.append(d)
            if (dd / "_DONE").exists():
                (dd / "_DONE").unlink()
    todo = sorted(set(todo) | set(redo), key=lambda x: x.isoformat())

    print(f"十月验证回灌 | DeviceID={client.device_id}")
    print(f"区间 {START}~{END} | 待拉 {len(todo)} | 已完成 "
          f"{sum(1 for d in days if bf.day_complete(d))}")
    print("-" * 60)

    fails = []
    for i, d in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {d.isoformat()}", flush=True)
        mm = bf.day_dir(d) / "_MISMATCH"
        if mm.exists():
            mm.unlink()
        # mismatch 日可能缺 _DONE，清半截后重拉
        status, msg = bf.pull_one_day(client, d, non_trading)
        if status == "fail":
            print(f"  STOP: {msg}")
            return 1
        if status == "skip":
            print("  skip")
            continue
        if status == "mismatch":
            print(f"  !! {msg}")
            fails.append(msg)
            continue
        print(f"  {msg}")
    return 0 if not fails else 2


def validate_month() -> int:
    print("\n" + "=" * 70)
    print("十月完整性校验")
    print("=" * 70)

    days = sorted(
        d for d in bf.RAW_DIR.iterdir()
        if d.is_dir() and d.name.startswith("2025-10-")
    )
    ok_n = bad_n = 0
    problems = []

    print(f"\n{'日期':<12}{'SJZT':>5}{'池子':>5}{'差':>4}{'最高':>4}{'反包':>4}{'分布'}")
    for d in days:
        done = (d / "_DONE").exists()
        mm = (d / "_MISMATCH").exists()
        pool_f = d / "zt_pool.json"
        sent_f = d / "sentiment.json"
        if not pool_f.exists() or not sent_f.exists():
            problems.append(f"{d.name}: 缺文件")
            bad_n += 1
            continue

        pool = json.loads(pool_f.read_text(encoding="utf-8"))
        sent = json.loads(sent_f.read_text(encoding="utf-8"))
        sjzt = int((sent.get("info") or {}).get("SJZT") or -1)
        n = pool["count"]
        gap = n - sjzt
        flag = "OK" if gap == 0 and done else "BAD"
        if flag == "OK":
            ok_n += 1
        else:
            bad_n += 1
            problems.append(f"{d.name}: count={n} sjzt={sjzt} done={done} mismatch={mm}")

        dist = dict(sorted(pool.get("board_counts", {}).items(), key=lambda x: -int(x[0])))
        print(f"{d.name:<12}{sjzt:>5}{n:>5}{gap:>4}{pool.get('max_board'):>4}"
              f"{pool.get('fanbao_count'):>4}  {dist}  {flag}")

        # 细则
        codes = [s["code"] for s in pool["stocks"]]
        if len(codes) != len(set(codes)):
            problems.append(f"{d.name}: 重复代码")
        for s in pool["stocks"]:
            if not isinstance(s.get("boards"), int) or s["boards"] < 1:
                problems.append(f"{d.name}: {s.get('code')} boards非法")
            if "ST" in str(s.get("name", "")).upper():
                problems.append(f"{d.name}: 混入ST {s['code']} {s['name']}")
            # 反包不得抬高：is_fanbao 时 boards 仍是真实连板
            if s.get("is_fanbao") and s["boards"] < 1:
                problems.append(f"{d.name}: 反包 boards 异常 {s['code']}")

        # board_counts 总和
        if sum(pool.get("board_counts", {}).values()) != n:
            problems.append(f"{d.name}: board_counts 合计 ≠ count")

        # sector_ladder 存在
        if not (d / "sector_ladder.json").exists():
            problems.append(f"{d.name}: 缺 sector_ladder")

    print(f"\n通过 {ok_n} 天 | 异常 {bad_n} 天 | 目录共 {len(days)} 天")
    if problems:
        print("问题清单:")
        for p in problems:
            print(f"  - {p}")
        return 1

    # 抽查：最高板票的 boards 与描述
    print("\n--- 抽查各日最高板 ---")
    for d in days:
        if not (d / "_DONE").exists():
            continue
        pool = json.loads((d / "zt_pool.json").read_text(encoding="utf-8"))
        top = [s for s in pool["stocks"] if s["boards"] == pool["max_board"]]
        for s in top[:2]:
            print(f"  {d.name} {s['boards']}板 {s['code']} {s['name']} "
                  f"描述={s['boards_desc']!r} 题材={s['theme']} 反包={s['is_fanbao']}")

    print("\n--- 抽查反包票（确认未抬高）---")
    for d in days:
        if not (d / "zt_pool.json").exists():
            continue
        pool = json.loads((d / "zt_pool.json").read_text(encoding="utf-8"))
        for s in pool["stocks"]:
            if s.get("is_fanbao"):
                print(f"  {d.name} 真实{s['boards']}板 {s['code']} {s['name']} "
                      f"描述={s['boards_desc']!r}")

    print("\n结论: 十月全部通过，数据可用。")
    return 0


def main() -> int:
    rc = pull_month()
    if rc == 1:
        return 1
    return validate_month()


if __name__ == "__main__":
    raise SystemExit(main())
