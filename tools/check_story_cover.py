# -*- coding: utf-8 -*-
"""覆盖检查：日级故事 vs 原图；是否含可选个股 stocks。不改数据。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ultraboard.ths.stories import load_day  # noqa: E402


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
    miss = [d for d in img if d not in set(have)]
    bad: list[tuple[str, str]] = []
    ws: list[str] = []
    for p in files:
        day = p.stem
        try:
            payload = load_day(day)
        except Exception as exc:  # noqa: BLE001 — report any load failure
            bad.append((day, str(exc)))
            continue
        if any(
            isinstance(item, dict) and item.get("stocks")
            for item in payload.get("stories") or []
        ):
            ws.append(day)
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
    )
    print("with_stocks_days", ws[:20])
    print("next", miss[0] if miss else None)
    # 全量门闩：有图日必须有故事文件；load_day 全过。
    # with_stocks 是否为 0 仅报告；个股层完整性由人工/抽查按 README 核对。
    if miss or bad or not img:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
