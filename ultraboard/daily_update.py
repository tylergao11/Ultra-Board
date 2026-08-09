# -*- coding: utf-8 -*-
"""更新一个完整交易日并原子发布到本地 Agent API。

默认目标是同花顺官方复盘页已经公开的最新交易日；显式 ``--date``
严格执行指定日期，不自动回退。来源层允许留下可诊断的未完成产物，公开 release
只有在全部合同通过后才会原子切换。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from ultraboard.day_facts import build_day_component
from ultraboard.kaipanla import load_day as load_kaipanla_day
from ultraboard.kaipanla.backfill import main as kaipanla_backfill_main
from ultraboard.ths.fupan_stories import ensure_day as ensure_story_day
from ultraboard.ths.fupan_stories import latest_available_day
from ultraboard.ths.limit_pool import load_day as load_limit_day


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "data" / ".daily_update.lock"
KPL_RAW_DIR = ROOT / "data" / "kaipanla" / "raw"
THS_LIMIT_DIR = ROOT / "data" / "ths" / "limit_pool"
CN_TZ = timezone(timedelta(hours=8))


@contextmanager
def _update_lock() -> Iterator[None]:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        owner = LOCK_PATH.read_text(encoding="utf-8-sig")
        raise RuntimeError(f"已有每日数据更新正在运行: {owner.strip()}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                {
                    "pid": os.getpid(),
                    "started_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
                },
                handle,
                ensure_ascii=False,
            )
            handle.write("\n")
        yield
    finally:
        if LOCK_PATH.exists():
            LOCK_PATH.unlink()


def _ensure_kaipanla(day: str) -> dict[str, Any]:
    directory = KPL_RAW_DIR / day
    if (directory / "_MISMATCH").exists():
        raise RuntimeError(f"{day} 开盘啦来源仍有 _MISMATCH，停止发布")
    existed = (directory / "_DONE").exists()
    if not existed:
        result = kaipanla_backfill_main(["--start", day, "--end", day])
        if result != 0:
            raise RuntimeError(f"{day} 开盘啦采集失败: exit={result}")
    payload = load_kaipanla_day(day)
    print(
        f"{'CHECKED' if existed else 'FETCHED'} {day} "
        f"kaipanla_stocks={len(payload['stocks'])}"
    )
    return payload


def _ensure_limit_pool(day: str) -> dict[str, Any]:
    existed = (THS_LIMIT_DIR / f"{day}.json").exists()
    payload = load_limit_day(day, fetch_missing=True)
    if payload is None:
        raise RuntimeError(f"{day} 同花顺涨停池采集后仍不可用")
    print(
        f"{'CHECKED' if existed else 'FETCHED'} {day} "
        f"ths_limit_stocks={payload['count']}"
    )
    return payload


def _require_complete_day(day: str) -> dict[str, Any]:
    component = build_day_component(day)
    coverage = component["coverage"]
    required = (
        "kpl_ready",
        "ths_limit_pool_ready",
        "ths_story_ready",
        "stock_story_complete",
        "fact_ready",
    )
    missing = [name for name in required if coverage.get(name) is not True]
    if missing:
        raise RuntimeError(
            f"{day} 完整性门禁失败: {missing}; "
            f"coverage={json.dumps(coverage, ensure_ascii=False)}"
        )
    if component.get("source_issues"):
        raise RuntimeError(
            f"{day} 来源集合未闭合: "
            f"{json.dumps(component['source_issues'], ensure_ascii=False)}"
        )
    return component


def _extract_api_envelope(stdout: str) -> dict[str, Any]:
    marker = '{\n  "schema_version"'
    offset = stdout.find(marker)
    if offset < 0:
        marker = '{"schema_version"'
        offset = stdout.find(marker)
    if offset < 0:
        raise RuntimeError(f"Agent API 输出中没有 JSON 外壳: {stdout[-500:]}")
    payload = json.loads(stdout[offset:])
    if not isinstance(payload, dict):
        raise RuntimeError("Agent API 输出顶层不是对象")
    return payload


def _call_api(endpoint: str, *, public_root: Path | None = None) -> dict[str, Any]:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        raise RuntimeError("找不到 npm，无法完成 Agent API 验证")
    environment = os.environ.copy()
    if public_root is not None:
        environment["ULTRA_BOARD_PUBLIC_ROOT"] = str(public_root.resolve())
    completed = subprocess.run(
        [npm, "run", "api", "--", endpoint],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Agent API 调用失败: {endpoint}\n"
            f"{completed.stdout[-1000:]}\n{completed.stderr[-1000:]}"
        )
    envelope = _extract_api_envelope(completed.stdout)
    response = envelope.get("response") or {}
    if response.get("status") != 200 or response.get("ok") is not True:
        raise RuntimeError(
            f"Agent API 验证未通过: {endpoint} "
            f"{json.dumps(response, ensure_ascii=False)}"
        )
    body = response.get("body")
    if not isinstance(body, dict):
        raise RuntimeError(f"Agent API 响应正文异常: {endpoint}")
    return body


def _verify_api_release(
    day: str,
    manifest: dict[str, Any],
    *,
    public_root: Path | None = None,
) -> None:
    health = _call_api("/api/v1/health", public_root=public_root)
    calendar = _call_api("/api/v1/calendar", public_root=public_root)
    api_day = _call_api(f"/api/v1/day?date={day}", public_root=public_root)
    revision = manifest["data_revision"]
    expected_end = manifest["range"]["end"]
    available_dates = calendar.get("available_dates") or []
    health_data = health.get("data") or {}
    if (
        health_data.get("revision") != revision
        or health_data.get("publication_ready") is not True
        or (health_data.get("range") or {}).get("end") != expected_end
    ):
        raise RuntimeError("Agent API health 与待发布 manifest 不一致")
    if (
        calendar.get("data_revision") != revision
        or calendar.get("publication_ready") is not True
        or calendar.get("range") != manifest["range"]
        or available_dates != manifest["available_dates"]
        or calendar.get("count") != len(available_dates)
        or day not in available_dates
    ):
        raise RuntimeError("Agent API calendar 与待发布 manifest 不一致")
    if (
        api_day.get("data_revision") != revision
        or api_day.get("trade_date") != day
        or api_day.get("information_cutoff") != day
        or not (api_day.get("coverage") or {}).get("fact_ready")
        or not (api_day.get("coverage") or {}).get("stock_story_complete")
    ):
        raise RuntimeError(f"Agent API 未完整返回目标交易日: {day}")


def _safe_rmtree(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    expected_parent = parent.resolve()
    if resolved.parent != expected_parent:
        raise RuntimeError(f"拒绝清理非预期临时目录: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def _publish(day: str) -> dict[str, Any]:
    from tools.export_agent_site_data import DEFAULT_OUTPUT, export_components

    output_dir = DEFAULT_OUTPUT.resolve()
    current_manifest_path = output_dir / "manifest.json"
    if current_manifest_path.exists():
        current_manifest = json.loads(
            current_manifest_path.read_text(encoding="utf-8-sig")
        )
        release_start = str(current_manifest["range"]["start"])
        current_end = str(current_manifest["range"]["end"])
        release_end = max(day, current_end)
    else:
        from ultraboard.day_facts import available_days

        days = [candidate for candidate in available_days() if candidate <= day]
        if not days:
            raise RuntimeError(f"{day} 之前没有可构建的正式来源日")
        release_start = days[0]
        release_end = day

    site_root = (ROOT / "site").resolve()
    temporary_root = Path(
        tempfile.mkdtemp(prefix=".daily-release-", dir=site_root)
    ).resolve()
    staged_output = temporary_root / "agent-data" / "v1"
    backup = output_dir.with_name(f".{output_dir.name}.{os.getpid()}.daily-backup")
    if backup.exists():
        raise RuntimeError(f"发现未处理的 release 备份，停止更新: {backup}")
    activated = False
    try:
        manifest = export_components(
            output_dir=staged_output,
            start=release_start,
            end=release_end,
            ready_only=False,
        )
        if (
            day not in manifest["available_dates"]
            or manifest["range"]["end"] != release_end
        ):
            raise RuntimeError(f"{day} 未进入待发布 release manifest")

        _verify_api_release(day, manifest, public_root=temporary_root)

        output_dir.parent.mkdir(parents=True, exist_ok=True)
        if output_dir.exists():
            os.replace(output_dir, backup)
        try:
            os.replace(staged_output, output_dir)
            activated = True
            _verify_api_release(day, manifest)
        except Exception:
            failed_output = temporary_root / "failed-active-release"
            if output_dir.exists():
                os.replace(output_dir, failed_output)
            if backup.exists():
                os.replace(backup, output_dir)
            activated = False
            raise

        if backup.exists():
            _safe_rmtree(backup, output_dir.parent)
        return manifest
    finally:
        if not activated and backup.exists() and not output_dir.exists():
            os.replace(backup, output_dir)
        _safe_rmtree(temporary_root, site_root)


def update_day(day_value: str) -> dict[str, Any]:
    day = date.fromisoformat(day_value).isoformat()
    _ensure_kaipanla(day)
    _ensure_limit_pool(day)
    story_payload, story_action = ensure_story_day(day)
    story_stock_count = len(story_payload.get("stock_stories") or [])
    if not story_stock_count:
        story_stock_count = sum(
            len(group.get("stocks") or [])
            for group in story_payload.get("stories") or []
            if isinstance(group, dict)
        )
    print(
        f"{story_action.upper()} {day} stories_source={story_payload['source']} "
        f"stock_stories={story_stock_count}"
    )
    component = _require_complete_day(day)
    manifest = _publish(day)
    market = component["market"]
    market_summary_keys = (
        "kaipanla_stock_count",
        "ths_limit_up_count",
        "first_board_count",
        "higher_board_count",
        "max_boards",
        "max_board_holders",
        "board_counts",
        "market_mood",
        "rise_count",
        "fall_count",
        "limit_down_count",
        "natural_limit_down_count",
    )
    return {
        "target_date": day,
        "market": {key: market.get(key) for key in market_summary_keys},
        "coverage": component["coverage"],
        "story_source": story_payload["source"],
        "release": {
            "range": manifest["range"],
            "available_dates": manifest["counts"]["available_dates"],
            "revision": manifest["data_revision"],
        },
        "api_verified": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        help=(
            "严格更新指定交易日 YYYY-MM-DD；省略时采用同花顺官方复盘页"
            "已经公开的最新交易日"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    official_latest = latest_available_day()
    target = date.fromisoformat(args.date).isoformat() if args.date else official_latest
    if target > official_latest:
        raise RuntimeError(
            f"指定日期尚未进入同花顺官方收盘复盘: "
            f"target={target}, latest={official_latest}"
        )
    mode = "explicit" if args.date else "latest_official_close_recap"
    print(f"TARGET {target} mode={mode}")
    with _update_lock():
        result = update_day(target)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
