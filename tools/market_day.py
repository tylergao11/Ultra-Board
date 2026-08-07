# -*- coding: utf-8 -*-
"""按日期输出一个交易日的市场事实，默认包含全部首板和高板。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ultraboard.day_facts import build_day_facts  # noqa: E402


def _write_json_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("date", help="交易日 YYYY-MM-DD")
    parser.add_argument(
        "--theme",
        action="append",
        default=[],
        help="精确开盘啦主/候选属性；可重复",
    )
    parser.add_argument(
        "--theme-match",
        choices=("any", "all"),
        default="any",
        help="多个题材任一命中或全部命中",
    )
    parser.add_argument(
        "--board",
        action="append",
        default=[],
        type=int,
        help="精确同花顺板数；可重复，不得与板数范围同时使用",
    )
    parser.add_argument("--min-board", type=int)
    parser.add_argument("--max-board", type=int)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    payload = build_day_facts(
        args.date,
        themes=args.theme,
        theme_match=args.theme_match,
        boards=args.board,
        min_board=args.min_board,
        max_board=args.max_board,
    )
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=None if args.compact else 2,
        separators=(",", ":") if args.compact else None,
    ) + "\n"
    if args.output:
        _write_json_atomic(args.output.resolve(), text)
        print(args.output.resolve())
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
