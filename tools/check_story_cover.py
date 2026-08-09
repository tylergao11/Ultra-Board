# -*- coding: utf-8 -*-
"""覆盖检查：正式交易日故事文件与逐股故事是否完整。不改数据。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ultraboard.ths.stories import load_day  # noqa: E402
from ultraboard.day_facts import build_day_component  # noqa: E402


def main() -> int:
    img = sorted(
        {
            f"{p.stem[:4]}-{p.stem[4:6]}-{p.stem[6:]}"
            for p in (ROOT / "data/ths/strong_wind_images").rglob("*.png")
            if len(p.stem) == 8 and p.stem.isdigit()
        }
    )
    files = sorted(
        p
        for p in (ROOT / "data/ths/stories").glob("*.json")
        if len(p.stem) == 10 and p.stem[4] == "-" and p.stem[7] == "-"
    )
    have = [p.stem for p in files]
    kpl = {
        path.name
        for path in (ROOT / "data/kaipanla/raw").iterdir()
        if path.is_dir() and (path / "_DONE").exists() and not (path / "_MISMATCH").exists()
    }
    limit_pool = {
        path.stem
        for path in (ROOT / "data/ths/limit_pool").glob("*.json")
    }
    required = sorted(kpl & limit_pool)
    miss = [day for day in required if day not in set(have)]
    bad: list[tuple[str, str]] = []
    ws: list[str] = []
    incomplete: list[tuple[str, list[str]]] = []
    for p in files:
        day = p.stem
        try:
            payload = load_day(day)
        except Exception as exc:  # noqa: BLE001 — report any load failure
            bad.append((day, str(exc)))
            continue
        if payload.get("stock_stories") or any(
            isinstance(item, dict) and item.get("stocks")
            for item in payload.get("stories") or []
        ):
            ws.append(day)
        coverage = build_day_component(day)["coverage"]
        if not coverage.get("stock_story_complete"):
            incomplete.append(
                (day, list(coverage.get("stock_story_missing_codes") or []))
            )
    print(
        "images",
        len(img),
        "stories",
        len(have),
        "missing",
        len(miss),
        "bad",
        len(bad),
        "with_stocks",
        len(ws),
        "incomplete",
        len(incomplete),
    )
    print("with_stocks_days", ws[:20])
    print("next", miss[0] if miss else None)
    if incomplete:
        print("incomplete_days", incomplete[:20])
    # 全量门闩：闭合的 KPL/THS 交易日必须有故事，且逐股故事覆盖完整。
    if miss or bad or incomplete or not required:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
