# -*- coding: utf-8 -*-
"""按同花顺“最强风口”真相识别节点日并冻结进攻/防守梯队。

题材、公告身份和风口排名只读取 ``data/ths/strong_wind``；板数、封板
时间与板型只读取 ``data/ths/limit_pool``。整条数据链均来自同花顺。

用法：

  python -m ultraboard.ths.ladder_selector list 2025-10-01 2025-12-31
  python -m ultraboard.ths.ladder_selector list 2026-08-06 2026-08-06 --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

from ultraboard.ths.limit_pool import validate_payload

ROOT = Path(__file__).resolve().parents[2]
THS_DIR = ROOT / "data" / "ths" / "strong_wind"
THS_IMAGE_DIR = ROOT / "data" / "ths" / "strong_wind_images"
LIMIT_POOL_DIR = ROOT / "data" / "ths" / "limit_pool"

# 只解释同花顺或人工审核后已经落成的明确分组名，不做事件关键词推断。
ANNOUNCEMENT_GROUP_TITLES = frozenset({
    "公告",
    "公告题材",
    "并购重组",
    "股权转让",
    "并购重组/股权转让",
    "股权转让/并购重组",
    "实控人变更",
    "ST摘帽",
    "业绩预增",
    "年报预增",
    "三季报预增",
    "三季报增长",
})
FALLBACK_GROUP_TITLES = frozenset({"其他", "其他概念", "其它概念", "未分类"})
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CODE_RE = re.compile(r"^\d{6}$")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    body = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(body, dict):
        raise ValueError(f"JSON 顶层不是对象: {path}")
    return body


def _code(value: Any) -> str:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    if not text.isdigit() or len(text) > 6:
        return ""
    return text.zfill(6)


def _is_announcement_group(title: str) -> bool:
    return title in ANNOUNCEMENT_GROUP_TITLES


def _source_image(body: dict[str, Any], path: Path) -> str:
    source_image = body.get("source_image")
    if not isinstance(source_image, str) or not source_image.strip():
        raise ValueError(f"同花顺原图路径缺失: {path}")
    image_path = (ROOT / source_image).resolve()
    try:
        image_path.relative_to(THS_IMAGE_DIR.resolve())
    except ValueError as exc:
        raise ValueError(f"同花顺原图越出证据目录: {source_image}") from exc
    if not image_path.is_file():
        raise ValueError(f"同花顺原图不存在: {source_image}")
    return source_image


def _ths_groups(day: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    path = THS_DIR / f"{day}.json"
    body = _load_json(path)
    if body.get("date") != day or body.get("source") != "tonghuashun_strong_wind":
        raise ValueError(f"同花顺日期或来源不一致: {path}")
    _source_image(body, path)

    issues = body.get("issues", [])
    if not isinstance(issues, list):
        raise ValueError(f"同花顺 issues 结构异常: {path}")
    if issues:
        raise ValueError(f"同花顺日文件仍有 {len(issues)} 个待处理问题: {path}")

    groups = body.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError(f"同花顺 groups 缺失或为空: {path}")

    stock_map: dict[str, dict[str, Any]] = {}
    for expected_rank, group in enumerate(groups, 1):
        if not isinstance(group, dict):
            raise ValueError(f"同花顺分组不是对象: {path} rank={expected_rank}")
        rank = group.get("rank")
        title = group.get("title")
        stocks = group.get("stocks")
        if rank != expected_rank or not isinstance(title, str) or not title.strip():
            raise ValueError(f"同花顺分组顺序或标题异常: {path} rank={expected_rank}")
        title = title.strip()
        if title in FALLBACK_GROUP_TITLES:
            raise ValueError(f"同花顺兜底分组尚未逐股人工审核: {day} {title}")
        if not isinstance(stocks, list) or not stocks:
            raise ValueError(f"同花顺分组股票表缺失或为空: {path} rank={rank}")
        for stock in stocks:
            if not isinstance(stock, dict):
                raise ValueError(f"同花顺股票行不是对象: {path} rank={rank}")
            code = _code(stock.get("code"))
            name = stock.get("name")
            if not CODE_RE.fullmatch(code) or not isinstance(name, str) or not name.strip():
                raise ValueError(f"同花顺股票必填字段异常: {path} rank={rank}")
            if code in stock_map:
                raise ValueError(f"同花顺股票存在多个主归属: {day} {code}")
            stock_map[code] = {
                "name": name.strip(),
                "group": title,
                "rank": rank,
                "announcement": _is_announcement_group(title),
            }
    return groups, stock_map


def _stocks(day: str) -> list[dict[str, Any]]:
    pool_path = LIMIT_POOL_DIR / f"{day}.json"
    pool = _load_json(pool_path)
    validate_payload(pool, day, pool_path)
    source = pool.get("source") or {}
    pool_stocks = pool.get("stocks")
    if (
        pool.get("date") != day
        or source.get("provider") != "tonghuashun_limit_up_pool"
        or not isinstance(pool_stocks, list)
        or pool.get("count") != len(pool_stocks)
    ):
        raise ValueError(f"同花顺涨停池合同异常: {pool_path}")

    _, ths = _ths_groups(day)
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    seen: set[str] = set()
    for stock in pool_stocks:
        if not isinstance(stock, dict):
            raise ValueError(f"同花顺涨停池出现非对象股票行: {pool_path}")
        code = _code(stock.get("code"))
        if not CODE_RE.fullmatch(code) or code in seen:
            raise ValueError(f"同花顺涨停池代码异常或重复: {day} {code!r}")
        seen.add(code)
        group = ths.get(code)
        if group is None:
            missing.append(f"{code} {stock.get('name') or ''}".strip())
            continue
        height = stock.get("boards")
        if isinstance(height, bool) or not isinstance(height, int) or height < 1:
            raise ValueError(f"同花顺连板数异常: {day} {code} {height!r}")
        one_price = stock.get("one_price")
        if not isinstance(one_price, bool):
            raise ValueError(f"同花顺真一字字段异常: {day} {code}")
        rows.append({
            "code": code,
            "name": group["name"],
            "height": height,
            "one_price": one_price,
            "boards_desc": stock.get("boards_desc"),
            "board_type": stock.get("board_type"),
            "first_limit_ts": stock.get("first_limit_ts"),
            "final_limit_ts": stock.get("final_limit_ts"),
            "open_count": stock.get("open_count"),
            **group,
        })
    if missing:
        preview = "、".join(missing[:20])
        suffix = "……" if len(missing) > 20 else ""
        raise ValueError(
            f"同花顺主分组缺少当天涨停股 {len(missing)} 只: {day} {preview}{suffix}"
        )
    rows.sort(key=lambda row: (-row["height"], row["rank"], row["code"]))
    return rows


def detect_node(day: str, previous_day: str) -> dict[str, Any]:
    previous = [
        row
        for row in _stocks(previous_day)
        if row["height"] >= 2 and not row["announcement"]
    ]
    if not previous:
        return {
            "date": day,
            "previous_date": previous_day,
            "is_node": False,
            "previous_height": None,
            "previous_leaders": [],
            "continued": [],
            "reason": "上一交易日没有二板及以上有效自然梯队",
        }

    height = max(row["height"] for row in previous)
    leaders = [row for row in previous if row["height"] == height]
    current = {row["code"]: row for row in _stocks(day)}
    continued = [
        current[row["code"]]
        for row in leaders
        if row["code"] in current and current[row["code"]]["height"] == height + 1
    ]
    if continued:
        names = "、".join(row["name"] for row in continued)
        reason = f"最高有效自然梯队仍有 {names} 晋级 {height + 1} 板"
    else:
        reason = f"上一交易日 {height} 板有效自然梯队全部断板"
    return {
        "date": day,
        "previous_date": previous_day,
        "is_node": not continued,
        "previous_height": height,
        "previous_leaders": leaders,
        "continued": continued,
        "reason": reason,
    }


def _with_roles(layer: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in layer:
        item = dict(row)
        if row["announcement"]:
            item["role"] = "公告量能" if row["one_price"] else "公告结构"
        elif row["one_price"]:
            item["role"] = "自然一字候选"
        else:
            item["role"] = "自然换手候选"
        result.append(item)
    return result


def freeze_ladder(day: str, trigger: dict[str, Any]) -> dict[str, Any]:
    all_rows = _stocks(day)
    rows = [row for row in all_rows if row["height"] >= 2]
    by_height: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_height.setdefault(row["height"], []).append(row)

    natural = [row for row in rows if not row["announcement"]]
    natural_highest = max((row["height"] for row in natural), default=None)

    attack: list[dict[str, Any]] = []
    if natural_highest is not None:
        for row in natural:
            if row["height"] != natural_highest or row["rank"] > 2:
                continue
            support = [
                peer
                for peer in all_rows
                if peer["group"] == row["group"]
                and peer["code"] != row["code"]
                and peer["height"] < row["height"]
            ]
            if support:
                attack.append({**row, "low_support": support})

    defense: dict[str, Any] | None = None
    for height in sorted({row["height"] for row in natural}, reverse=True):
        layer = by_height[height]
        natural_layer = [row for row in layer if not row["announcement"]]
        anchors = [row for row in layer if row["one_price"]]
        if natural_layer and anchors:
            defense = {"height": height, "anchors": anchors}
            break

    secondary_model: str | None = None
    secondary_height: int | None = None
    secondary_layer: list[dict[str, Any]] = []
    if attack:
        target_height = natural_highest
        model = "进攻模型"
        if defense is not None:
            secondary_model = "防守模型"
            secondary_height = defense["height"]
            secondary_layer = _with_roles(by_height[secondary_height])
    elif defense is not None:
        target_height = defense["height"]
        model = "防守模型"
    elif any(row["height"] == 2 for row in natural):
        target_height = 2
        model = "无模型"
    else:
        target_height = None
        model = "无模型"

    selected = _with_roles(by_height.get(target_height, [])) if target_height else []
    return {
        "date": day,
        "information_cutoff": day,
        "node_trigger": trigger,
        "natural_highest": natural_highest,
        "target_height": target_height,
        "model": model,
        "secondary_model": secondary_model,
        "secondary_height": secondary_height,
        "attack_candidates": attack,
        "defense_structure": defense,
        "selected_layer": selected,
        "secondary_layer": secondary_layer,
    }


def _ths_days() -> list[str]:
    days = [path.stem for path in THS_DIR.glob("*.json") if DAY_RE.fullmatch(path.stem)]
    return sorted(days)


def _require_objective_day(day: str) -> None:
    path = LIMIT_POOL_DIR / f"{day}.json"
    if not path.is_file():
        raise FileNotFoundError(f"缺少 {day} 同花顺涨停池: {path}")


def list_nodes(start: str, end: str) -> dict[str, Any]:
    start_day = date.fromisoformat(start)
    end_day = date.fromisoformat(end)
    if start_day > end_day:
        raise ValueError("start 不能晚于 end")

    all_days = _ths_days()
    days = [day for day in all_days if start <= day <= end]
    if not days:
        raise ValueError(f"区间内没有同花顺逐日真相: {start} 至 {end}")
    for day in days:
        _require_objective_day(day)

    first_index = all_days.index(days[0])
    boundary: str | None = None
    if first_index == 0:
        boundary = f"{days[0]} 之前没有同花顺逐日真相，无法判断该日是否为节点"
        pairs = zip(days, days[1:])
    else:
        previous = all_days[first_index - 1]
        _require_objective_day(previous)
        pairs = zip([previous, *days[:-1]], days)

    nodes: list[dict[str, Any]] = []
    for previous, day in pairs:
        trigger = detect_node(day, previous)
        if trigger["is_node"]:
            nodes.append(freeze_ladder(day, trigger))

    return {
        "source": "tonghuashun_strong_wind+limit_up_pool",
        "start": start,
        "end": end,
        "trade_day_count": len(days),
        "boundary_warning": boundary,
        "node_count": len(nodes),
        "nodes": nodes,
    }


def _stock_text(row: dict[str, Any]) -> str:
    shape = "一字" if row["one_price"] else "换手"
    return f"{row['name']}({row['code']}，{row['group']}，{shape}，{row['role']})"


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# 同花顺最强风口节点日与冻结梯队",
        "",
        (
            f"区间：{result['start']} 至 {result['end']}；"
            f"交易日 {result['trade_day_count']}；节点日 {result['node_count']}"
        ),
    ]
    if result["boundary_warning"]:
        lines.extend(["", f"> 边界：{result['boundary_warning']}"])
    lines.extend([
        "",
        "|节点日|断板前最高层|冻结梯队|模型|梯队成员|",
        "|---|---:|---:|---|---|",
    ])
    for node in result["nodes"]:
        trigger = node["node_trigger"]
        previous = "、".join(row["name"] for row in trigger["previous_leaders"])
        before = f"{trigger['previous_height']}板（{previous}）"
        target = f"{node['target_height']}板" if node["target_height"] else "不选层"
        model = node["model"]
        if node["secondary_model"]:
            model += f"（次级{node['secondary_model']}@{node['secondary_height']}板）"
        members = "；".join(_stock_text(row) for row in node["selected_layer"]) or "—"
        lines.append(f"|{node['date']}|{before}|{target}|{model}|{members}|")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list", help="列出区间内节点日与冻结梯队")
    list_parser.add_argument("start")
    list_parser.add_argument("end")
    list_parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = list_nodes(args.start, args.end)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(markdown(result))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
