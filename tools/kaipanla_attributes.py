# -*- coding: utf-8 -*-
"""采集、查询和校验开盘啦历史板块成分研究快照。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ultraboard.kaipanla import KaipanlaClient  # noqa: E402
from ultraboard.kaipanla.attributes import (  # noqa: E402
    ATTRIBUTE_DIR,
    available_plate_snapshots,
    capture_plate_membership,
    membership_index,
)


def _capture(args: argparse.Namespace) -> dict[str, object]:
    client = KaipanlaClient(ROOT / "data" / "kaipanla", 0.5, 1.0)
    payload = capture_plate_membership(
        client,
        args.date,
        args.plate_code,
        plate_name=args.name,
        overwrite=args.force,
    )
    return {
        "view": payload["view"],
        "date": payload["query"]["date"],
        "plate_code": payload["query"]["plate_code"],
        "plate_name": payload["query"].get("plate_name"),
        "member_count": payload["member_count"],
        "output": str(
            ATTRIBUTE_DIR
            / payload["query"]["date"]
            / f"{payload['query']['plate_code']}.json"
        ),
    }


def _show(args: argparse.Namespace) -> dict[str, object]:
    code = str(args.code).strip().zfill(6)
    return {
        "view": "kaipanla_historical_stock_memberships",
        "date": args.date,
        "code": code,
        "memberships": membership_index(args.date).get(code, []),
    }


def _validate(args: argparse.Namespace) -> dict[str, object]:
    directories = []
    if ATTRIBUTE_DIR.exists():
        directories = [
            path
            for path in ATTRIBUTE_DIR.iterdir()
            if path.is_dir()
            and (args.start is None or path.name >= args.start)
            and (args.end is None or path.name <= args.end)
        ]
    files = 0
    members = 0
    days = []
    for directory in sorted(directories):
        snapshots = available_plate_snapshots(directory.name)
        files += len(snapshots)
        members += sum(int(item["member_count"]) for item in snapshots)
        days.append(
            {
                "date": directory.name,
                "plate_snapshot_count": len(snapshots),
            }
        )
    return {
        "view": "kaipanla_historical_attribute_validation",
        "plate_snapshot_count": files,
        "member_row_count": members,
        "days": days,
        "valid": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    capture = commands.add_parser("capture")
    capture.add_argument("date")
    capture.add_argument("plate_code")
    capture.add_argument("--name")
    capture.add_argument("--force", action="store_true")

    show = commands.add_parser("show")
    show.add_argument("date")
    show.add_argument("code")

    validate = commands.add_parser("validate")
    validate.add_argument("--start")
    validate.add_argument("--end")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    if args.command == "capture":
        payload = _capture(args)
    elif args.command == "show":
        payload = _show(args)
    elif args.command == "validate":
        payload = _validate(args)
    else:
        raise AssertionError(args.command)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
