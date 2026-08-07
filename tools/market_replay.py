# -*- coding: utf-8 -*-
"""输出五日动态事实包；日明细默认二板以上，动态路径从一进二开始。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ultraboard.replay import build_next_replay, build_replay  # noqa: E402


def _write_json_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("date", help="信息截止日或 --next 游标，YYYY-MM-DD")
    parser.add_argument(
        "--theme",
        action="append",
        default=[],
        help="精确匹配开盘啦主/候选属性；可重复，传入后包含首板",
    )
    parser.add_argument(
        "--include-all-first-boards",
        action="store_true",
        help=(
            "显式展开全市场全部涨停；默认日明细只展开二板以上，"
            "但动态路径仍回带已进入梯队股票的首板事实"
        ),
    )
    parser.add_argument(
        "--next",
        action="store_true",
        help="沿相同查询范围推进到下一个本地数据日",
    )
    parser.add_argument("--window-size", type=int, default=5)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    if args.window_size < 1:
        raise ValueError("--window-size 必须大于等于 1")

    kwargs = {
        "themes": args.theme,
        "window_size": args.window_size,
        "include_all_first_boards": args.include_all_first_boards,
    }
    payload = (
        build_next_replay(args.date, **kwargs)
        if args.next
        else build_replay(args.date, **kwargs)
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
