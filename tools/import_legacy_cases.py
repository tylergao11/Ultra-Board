# -*- coding: utf-8 -*-
"""把标准 CASE Markdown 段落一次性迁移为结构化案例记录。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "cases" / "manifest.json"
CASE_HEADING_RE = re.compile(r"^### (CASE-(\d{4}-\d{2}-\d{2}))[｜|](.+)$")
FIELD_RE = re.compile(r"^- \*\*(.+?)\*\*[：:](.*)$")
BOARD_NUMBER_RE = r"([一二三四五六七八九十\d]+)板"
CN_DIGITS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _manifest() -> dict[str, Any]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != 1:
        raise ValueError("案例 manifest 版本不受支持")
    return payload


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else ROOT / path


def _extract_sections(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    starts: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = CASE_HEADING_RE.fullmatch(line)
        if match:
            starts.append((index, match))
    sections: list[dict[str, Any]] = []
    for position, (start, match) in enumerate(starts):
        next_case = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        end = next_case
        for index in range(start + 1, next_case):
            if lines[index].startswith("### "):
                end = index
                break
        block_lines = lines[start:end]
        fields: dict[str, str] = {}
        for line in block_lines[1:]:
            field_match = FIELD_RE.fullmatch(line)
            if field_match:
                fields[field_match.group(1).strip()] = field_match.group(2).strip()
        sections.append(
            {
                "case_id": match.group(1),
                "setup_trade_date": match.group(2),
                "title": match.group(3).strip(),
                "heading": lines[start],
                "text": "\n".join(block_lines).strip() + "\n",
                "fields": fields,
                "source": path,
            }
        )
    return sections


def _trading_days() -> list[str]:
    days = [path.stem for path in (ROOT / "data" / "ths" / "limit_pool").glob("*.json")]
    return sorted(day for day in days if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day))


def _next_trading_day(day: str, days: list[str], offset: int = 1) -> str:
    try:
        position = days.index(day)
    except ValueError as exc:
        raise ValueError(f"缺少节点日涨停池: {day}") from exc
    target = position + offset
    if target >= len(days):
        raise ValueError(f"缺少 {day} 之后第 {offset} 个交易日")
    return days[target]


def _stocks(day: str) -> list[dict[str, Any]]:
    path = ROOT / "data" / "ths" / "limit_pool" / f"{day}.json"
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = payload.get("stocks")
    if not isinstance(rows, list):
        raise ValueError(f"涨停池 stocks 非法: {path}")
    return rows


def _market_max(day: str) -> int:
    boards = [row.get("boards") for row in _stocks(day)]
    values = [value for value in boards if isinstance(value, int) and not isinstance(value, bool)]
    if not values:
        raise ValueError(f"无法计算市场最高板: {day}")
    return max(values)


def _market_max_from_summary(height_summary: str, day: str) -> int:
    for sentence in re.split(r"[。；]", height_summary):
        position = sentence.find("市场最高")
        if position < 0:
            continue
        values = [_cn_int(raw) for raw in re.findall(BOARD_NUMBER_RE, sentence[position:])]
        if values:
            return values[0]
    return _market_max(day)


def _cn_int(raw: str) -> int:
    if raw.isdigit():
        return int(raw)
    if raw in CN_DIGITS:
        return CN_DIGITS[raw]
    if raw.startswith("十") and len(raw) == 2 and raw[1] in CN_DIGITS:
        return 10 + CN_DIGITS[raw[1]]
    if raw.endswith("十") and len(raw) == 2 and raw[0] in CN_DIGITS:
        return CN_DIGITS[raw[0]] * 10
    if len(raw) == 3 and raw[1] == "十" and raw[0] in CN_DIGITS and raw[2] in CN_DIGITS:
        return CN_DIGITS[raw[0]] * 10 + CN_DIGITS[raw[2]]
    raise ValueError(f"不支持的中文数字: {raw}")


def _first_board_number(text: str) -> int | None:
    match = re.search(BOARD_NUMBER_RE, text)
    return _cn_int(match.group(1)) if match else None


def _core_height(height_summary: str, decision_summary: str, market_max: int) -> int | None:
    markers = (
        "有意义核心",
        "有意义的核心",
        "有意义防守核心层",
        "真实可交易核心",
        "真实组织核心",
        "可组织的换手高度",
        "核心高度",
        "防守核心层",
    )
    for text in (height_summary, decision_summary):
        for sentence in re.split(r"[。；]", text):
            positions = [sentence.find(marker) for marker in markers if marker in sentence]
            if not positions:
                continue
            tail = sentence[min(positions) :]
            tail = re.sub(r"(?:低于|回到|进入)?七板(?:以上|以下)?(?:监管高度|环境)?", "", tail)
            directed = re.search(
                rf"(?:落在|落到|下移到|降到|均为|为|在)[^。；，]{{0,16}}?{BOARD_NUMBER_RE}",
                tail,
            )
            if directed:
                return _cn_int(directed.group(1))
            values = [_cn_int(raw) for raw in re.findall(BOARD_NUMBER_RE, tail)]
            if values:
                return values[0]
    if "防守" in decision_summary:
        value = _first_board_number(decision_summary)
        if value is not None:
            return value
    if "进攻" in decision_summary:
        value = _first_board_number(height_summary)
        if value is not None and value <= market_max:
            return value
    return None


def _model(text: str) -> str:
    if "进攻为主" in text and "防守" in text:
        return "offense_primary_defense_backup"
    if "无有效防守层" in text and "进攻" not in text:
        return "no_effective_defense"
    if "防守" in text and "进攻" not in text:
        return "defense"
    if "进攻" in text:
        return "offense"
    return "undetermined"


def _names_for_days(*days: str) -> list[str]:
    names = {
        row["name"]
        for day in days
        for row in _stocks(day)
        if isinstance(row.get("name"), str) and row["name"].strip()
    }
    return sorted(names, key=lambda value: (-len(value), value))


def _mentioned_names(text: str, names: list[str]) -> list[str]:
    positions = [(text.find(name), name) for name in names if name in text]
    return [name for _, name in sorted(positions) if _ >= 0]


def _name_after_phrase(text: str, phrases: list[str], names: list[str]) -> str | None:
    for phrase in phrases:
        position = text.find(phrase)
        if position < 0:
            continue
        tail = text[position + len(phrase) : position + len(phrase) + 40]
        found = _mentioned_names(tail, names)
        if found:
            return found[0]
    return None


def _selection(frozen_plan: str, closing: str, names: list[str]) -> dict[str, Any]:
    combined = frozen_plan + "\n" + closing
    primary = None
    for name in names:
        if any(
            phrase in combined
            for phrase in (
                f"{name}取得唯一可交易第一选择",
                f"{name}是唯一可交易第一选择",
                f"{name}为唯一可交易第一选择",
                f"{name}是唯一第一选择",
                f"{name}为唯一第一选择",
            )
        ):
            primary = name
            break
    if primary is None:
        primary = _name_after_phrase(
            combined,
            [
                "唯一可交易第一选择是",
                "唯一可交易第一选择为",
                "唯一第一选择是",
                "唯一第一选择为",
                "唯一第一选择",
                "第一选择已经是",
                "第一选择冻结为",
                "唯一目标转为",
                "次日只观察",
                "主进攻路径先看",
            ],
            names,
        )
    if primary is None:
        for name in names:
            if f"{name}是唯一可交易" in combined or f"{name}必须表现" in combined:
                primary = name
                break

    conditional: list[dict[str, str]] = []
    pair_match = None
    for left in names:
        for right in names:
            if left == right:
                continue
            token = f"{left}与{right}只按次日竞价选一只"
            if token in combined:
                pair_match = (left, right)
                break
        if pair_match:
            break
    if pair_match:
        primary = None
        conditional = [
            {"target": pair_match[0], "trigger": frozen_plan},
            {"target": pair_match[1], "trigger": frozen_plan},
        ]
    else:
        for name in names:
            if name == primary:
                continue
            if f"{name}只有在" in combined and "条件路径" in combined:
                conditional.append({"target": name, "trigger": frozen_plan})

    if conditional:
        mode = "conditional"
    elif primary is not None:
        mode = "unique"
    else:
        mode = "none"
    return {
        "selection_mode": mode,
        "primary_target": primary,
        "conditional_targets": conditional,
    }


def _split_tags(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[、,，]", value) if item.strip()]


def _trade_result(fields: dict[str, str]) -> str:
    judgement = " ".join(
        value
        for key, value in fields.items()
        if key in {"交易判卷", "T+1判卷", "T+1竞价与结果", "T+1打板结果"}
    )
    if "未触" in judgement or "无交易" in judgement:
        return "no_trade"
    if "未封住" in judgement or ("吃面" in judgement and "未吃面" not in judgement):
        return "failed_to_hold_limit"
    if "封住" in judgement or "成功" in judgement or "未吃面" in judgement:
        return "sealed_limit"
    return "pending"


def _replay_summary(fields: dict[str, str]) -> str:
    keys = (
        "T+1竞价裁决",
        "T+1竞价与结果",
        "T+1打板结果",
        "T+1判卷",
        "交易判卷",
    )
    values = [fields[key] for key in keys if fields.get(key)]
    return " ".join(dict.fromkeys(values))


def _follow_up(fields: dict[str, str]) -> str:
    values = [
        fields[key]
        for key in ("后续竞价反馈", "T+2反馈")
        if fields.get(key)
    ]
    return " ".join(values)


def _executed_target(
    trade_result: str,
    fields: dict[str, str],
    selection: dict[str, Any],
    names: list[str],
) -> str | None:
    if trade_result not in {"sealed_limit", "failed_to_hold_limit"}:
        return None
    result_specific = " ".join(
        fields.get(key, "") for key in ("T+1打板结果", "T+1判卷", "交易判卷")
    )
    candidates = []
    if selection["primary_target"]:
        candidates.append(selection["primary_target"])
    candidates.extend(item["target"] for item in selection["conditional_targets"])
    for name in candidates:
        if name in result_specific:
            return name
    mentioned = _mentioned_names(result_specific, names)
    if mentioned:
        return mentioned[0]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _record(
    section: dict[str, Any],
    compiled_at: str,
    trading_days: list[str],
) -> dict[str, Any]:
    fields = section["fields"]
    required_labels = ("条件标签", "结果标签", "发酵情况", "加速情况", "板型情况", "高度环境")
    missing = [label for label in required_labels if not fields.get(label)]
    if missing:
        raise ValueError(f"{section['case_id']} 缺少字段: {', '.join(missing)}")

    setup_day = section["setup_trade_date"]
    replay_day = _next_trading_day(setup_day, trading_days)
    follow_up = _follow_up(fields)
    outcome_day = _next_trading_day(setup_day, trading_days, 2) if follow_up else replay_day
    outcome_time = "15:00:00"
    market_max = _market_max_from_summary(fields["高度环境"], setup_day)
    closing = fields.get("收盘结构") or fields.get("收盘冻结") or fields["高度环境"]
    frozen_plan = fields.get("冻结计划") or fields.get("收盘冻结") or closing
    decision_summary = " ".join(
        value for value in (fields.get("模型判断"), fields.get("收盘冻结")) if value
    )
    model = _model(decision_summary)
    core_height = _core_height(fields["高度环境"], decision_summary, market_max)
    names = _names_for_days(setup_day, replay_day)
    selection = _selection(frozen_plan, closing, names)
    trade_result = _trade_result(fields)
    replay_summary = _replay_summary(fields)
    executed_target = _executed_target(trade_result, fields, selection, names)
    section_hash = hashlib.sha256(section["text"].encode("utf-8")).hexdigest()
    source_path = section["source"].relative_to(ROOT).as_posix()
    environment_summary = fields.get("相似环境摘要") or (
        f"{section['title']}；{fields['高度环境']}"
    )
    differences = [fields["过程观察"]] if fields.get("过程观察") else []
    defense_level = None
    if model == "defense":
        defense_level = core_height
    elif model == "offense_primary_defense_backup":
        defense_match = re.search(rf"{BOARD_NUMBER_RE}防守", decision_summary)
        if defense_match:
            defense_level = _cn_int(defense_match.group(1))

    record_id = f"{section['case_id']}@1"
    return {
        "schema_version": 1,
        "case_id": section["case_id"],
        "record_id": record_id,
        "revision": 1,
        "case_status": "closed",
        "retrieval_status": "accepted",
        "setup_trade_date": setup_day,
        "decision_cutoff": f"{setup_day}T15:00:00+08:00",
        "replay_trade_date": replay_day,
        "outcome_cutoff": f"{outcome_day}T{outcome_time}+08:00",
        "decision_record_mode": "blind_reconstruction",
        "decision_recorded_at": None,
        "case_compiled_at": compiled_at,
        "historical_replay_scope": "current_method_only",
        "title": section["title"],
        "case_question": section["title"],
        "source": {
            "kind": "legacy_markdown_migration",
            "document": source_path,
            "heading": section["heading"],
            "section_sha256": section_hash,
            "source_reports": [source_path],
            "data_revision": f"legacy-section-sha256:{section_hash}",
            "source_issues": [
                "decision_recorded_at_unverified",
                "legacy_case_sources_not_fully_enumerated",
            ],
        },
        "retrieval_tags": _split_tags(fields["条件标签"]),
        "condition_axes": {
            "fermentation": {"summary": fields["发酵情况"]},
            "acceleration": {"summary": fields["加速情况"]},
            "board_shape": {"summary": fields["板型情况"]},
            "height_environment": {
                "summary": fields["高度环境"],
                "market_max_boards": market_max,
                "meaningful_core_boards": core_height,
                "regulatory_height_present": market_max >= 7,
            },
        },
        "market_structure": {
            "is_node_day": True,
            "broken_core_summary": fields.get("断板核心") or fields["高度环境"],
            "closing_structure_summary": closing,
        },
        "decision": {
            "model": model,
            "defense_level_boards": defense_level,
            **selection,
            "frozen_plan": frozen_plan,
            "invalidation_conditions": [],
        },
        "outcome": {
            "trade_result": trade_result,
            "executed_target": executed_target,
            "replay_summary": replay_summary,
            "follow_up_summary": follow_up,
            "result_tags": _split_tags(fields["结果标签"]),
        },
        "similarity": {
            "environment_summary": environment_summary,
            "difference_boundaries": differences,
        },
        "legacy_fields": fields,
        "supersedes": [],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--source-glob", action="append", default=[])
    parser.add_argument("--compiled-at", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    compiled_at = datetime.fromisoformat(args.compiled_at.replace("Z", "+00:00"))
    if compiled_at.tzinfo is None:
        raise ValueError("--compiled-at 必须包含时区")
    manifest = _manifest()
    output_dir = (
        _resolve(args.output_dir)
        if args.output_dir
        else ROOT / Path(manifest["record_glob"]).parent
    )
    source_paths = [_resolve(source) for source in args.source]
    for pattern in args.source_glob:
        source_paths.extend(sorted(ROOT.glob(pattern)))
    source_paths = list(dict.fromkeys(source_paths))
    if not source_paths:
        raise ValueError("至少提供一个 --source 或 --source-glob")
    sections = [
        section
        for source in source_paths
        for section in _extract_sections(source)
    ]
    records = [_record(section, args.compiled_at, _trading_days()) for section in sections]
    if len({row["record_id"] for row in records}) != len(records):
        raise ValueError("迁移来源包含重复 record_id")
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        for row in records:
            output = output_dir / f"{row['record_id']}.json"
            if output.exists():
                raise FileExistsError(f"拒绝覆盖现有案例: {output}")
            output.write_text(
                json.dumps(row, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
    print(
        json.dumps(
            {
                "record_count": len(records),
                "record_ids": [row["record_id"] for row in records],
                "output_dir": str(output_dir),
                "dry_run": args.dry_run,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
