# -*- coding: utf-8 -*-
"""把同花顺节点结果导出为站点唯一可读的静态派生快照。

用法：

  python -m ultraboard.ths.site_export 2025-10-09 2026-01-30 \
    --output site/public/data/ths-nodes.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ultraboard.ths.ladder_selector import list_nodes

SCHEMA_VERSION = 2
SOURCE = "tonghuashun_strong_wind+limit_up_pool"
CN_TZ = ZoneInfo("Asia/Shanghai")


def _support_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": row["code"],
        "name": row["name"],
        "height": row["height"],
    }


def _stock_view(
    row: dict[str, Any],
    *,
    attack_support: dict[str, list[dict[str, Any]]],
    defense_anchors: set[str],
) -> dict[str, Any]:
    return {
        "code": row["code"],
        "name": row["name"],
        "height": row["height"],
        "boardsDesc": row["boards_desc"] or None,
        "limitUpWindowDays": row["limit_up_window_days"],
        "limitUpTotal": row["limit_up_total"],
        "boardsSource": row["boards_source"],
        "consecutiveLimitUpDates": row["consecutive_limit_up_dates"],
        "theme": row["group"],
        "themeRank": row["rank"],
        "themeDisplayRank": row["display_rank"],
        "themeAssignment": row["theme_assignment"],
        "posterRank": row["poster_rank"],
        "posterGroup": row["poster_group"],
        "isAnnouncement": row["announcement"],
        "boardType": row["board_type"],
        "onePrice": row["one_price"],
        "firstLimitTs": row["first_limit_ts"],
        "finalLimitTs": row["final_limit_ts"],
        "openCount": row["open_count"],
        "role": row.get("role"),
        "attackQualified": row["code"] in attack_support,
        "defenseAnchor": row["code"] in defense_anchors,
        "lowSupport": [
            _support_view(item) for item in attack_support.get(row["code"], [])
        ],
    }


def _node_view(node: dict[str, Any]) -> dict[str, Any]:
    attack_support = {
        row["code"]: row.get("low_support", [])
        for row in node["attack_candidates"]
    }
    defense = node.get("defense_structure")
    defense_anchors = {
        row["code"] for row in (defense or {}).get("anchors", [])
    }

    def stock(row: dict[str, Any]) -> dict[str, Any]:
        return _stock_view(
            row,
            attack_support=attack_support,
            defense_anchors=defense_anchors,
        )

    trigger = node["node_trigger"]
    secondary = None
    if node["secondary_model"] is not None:
        secondary = {
            "model": node["secondary_model"],
            "height": node["secondary_height"],
            "members": [stock(row) for row in node["secondary_layer"]],
        }

    model_reason = {
        "进攻模型": "最高自然梯队位于当日前二风口，且同题材有更低板助攻。",
        "防守模型": "冻结层同时存在自然票与真一字锚。",
        "无模型": "当日结构不满足进攻或防守模型，只保留客观梯队。",
    }[node["model"]]

    return {
        "nodeDate": node["date"],
        "dataCutoff": f"{node['information_cutoff']} 收盘",
        "naturalHighest": node["natural_highest"],
        "trigger": {
            "previousDate": trigger["previous_date"],
            "previousHeight": trigger["previous_height"],
            "previousLeaders": [stock(row) for row in trigger["previous_leaders"]],
            "reason": trigger["reason"],
        },
        "primary": {
            "model": node["model"],
            "height": node["target_height"],
            "reason": model_reason,
            "members": [stock(row) for row in node["selected_layer"]],
        },
        "secondary": secondary,
        "ladders": [
            {
                "height": ladder["height"],
                "count": ladder["count"],
                "naturalCount": ladder["natural_count"],
                "announcementCount": ladder["announcement_count"],
                "onePriceCount": ladder["one_price_count"],
                "members": [stock(row) for row in ladder["members"]],
            }
            for ladder in node["ladders"]
        ],
    }


def build_site_bundle(start: str, end: str) -> dict[str, Any]:
    result = list_nodes(start, end)
    nodes = [_node_view(node) for node in result["nodes"]]
    canonical = json.dumps(nodes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    revision = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "source": SOURCE,
        "generatedAt": datetime.now(CN_TZ).isoformat(timespec="seconds"),
        "revision": revision,
        "range": {"start": start, "end": end},
        "tradeDayCount": result["trade_day_count"],
        "boundaryWarning": result["boundary_warning"],
        "nodeCount": len(nodes),
        "nodes": nodes,
    }


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start")
    parser.add_argument("end")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = build_site_bundle(args.start, args.end)
    _write_atomic(args.output.resolve(), payload)
    print(
        f"WROTE {args.output} nodes={payload['nodeCount']} "
        f"revision={payload['revision']}"
    )
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
