# -*- coding: utf-8 -*-
"""查看某一秒附近，全体涨停和炸板股票发生了什么。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ultraboard.intraday_window import build_intraday_window  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("date", help="最近交易日 YYYY-MM-DD")
    parser.add_argument("time", help="中心时间 HH:MM:SS")
    parser.add_argument("--before", type=int, default=180, help="向前观察秒数")
    parser.add_argument("--after", type=int, default=180, help="向后观察秒数")
    parser.add_argument("--min-move", type=float, default=0.5, help="最低百分点动作")
    args = parser.parse_args(argv)
    payload = build_intraday_window(
        args.date,
        args.time,
        seconds_before=args.before,
        seconds_after=args.after,
        min_move_percentage_points=args.min_move,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

