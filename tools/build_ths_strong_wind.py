#!/usr/bin/env python3
"""Build reusable Tonghuashun "strong wind" daily classification JSON.

The official poster image remains the evidence source.  The daily limit-up pool
is used only to correct OCR stock codes/names.  Explicit poster groups are never
reclassified.  Stocks in fallback groups such as "其他概念" are reclassified
only after a human decision has been recorded in the manual review file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

try:
    import numpy as np
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR
except ImportError as exc:  # pragma: no cover - user-facing dependency check
    raise SystemExit(
        "Missing OCR dependency. Run: "
        f"{sys.executable} -m pip install rapidocr-onnxruntime Pillow numpy"
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE_ROOT = ROOT / "data" / "ths" / "strong_wind_images"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "ths" / "strong_wind"
DEFAULT_RAW_ROOT = ROOT / "data" / "kaipanla" / "raw"
DEFAULT_MANUAL_REVIEWS = ROOT / "data" / "ths" / "strong_wind_manual_reviews.json"

DATE_STEM_RE = re.compile(r"^\d{8}$")
CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
BOARD_TOKEN_RE = re.compile(r"^(?:首板|[一二三四五六七八九十百\d]+板|\d+天\d+板)$")
TIME_TOKEN_RE = re.compile(r"^\d{1,2}[:：]\d{2}(?:[:：]\d{2})?$")
TITLE_SPLIT_RE = re.compile(r"[：:]")
IMAGE_DATE_FORMAT = "%Y%m%d"
FALLBACK_GROUP_TITLES = frozenset({"其他", "其他概念", "未分类"})

_OCR_ENGINE: RapidOCR | None = None


@dataclass(frozen=True)
class Detection:
    x: float
    y: float
    text: str
    score: float


@dataclass
class ParsedStock:
    code: str
    name: str
    event_text: str


def get_ocr_engine() -> RapidOCR:
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value)).replace("Ａ", "A")


def normalize_code(value: Any) -> str:
    text = re.sub(r"\D", "", str(value))
    return text.zfill(6) if text else ""


def is_fallback_group(title: Any) -> bool:
    return normalize_text(str(title or "")) in FALLBACK_GROUP_TITLES


def parse_image_day(path: Path) -> str:
    return date(
        int(path.stem[0:4]), int(path.stem[4:6]), int(path.stem[6:8])
    ).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def add_stock_rows(target: dict[str, str], rows: Iterable[dict[str, Any]]) -> None:
    for row in rows:
        code = normalize_code(row.get("code", ""))
        name = str(row.get("name", "")).strip()
        if code and name:
            target[code] = name


def load_day_stock_map(raw_root: Path, day: str) -> dict[str, str]:
    day_dir = raw_root / day
    result: dict[str, str] = {}

    zt_pool_path = day_dir / "zt_pool.json"
    if zt_pool_path.exists():
        payload = load_json(zt_pool_path)
        add_stock_rows(result, payload.get("stocks", []))
        reconciliation = payload.get("source_reconciliation", {})
        add_stock_rows(result, reconciliation.get("excluded_bse", []))

    ths_pool_path = day_dir / "ths_limit_pool.json"
    if ths_pool_path.exists():
        add_stock_rows(result, load_json(ths_pool_path).get("stocks", []))

    if not result:
        raise FileNotFoundError(f"no daily stock pool found for {day}: {day_dir}")
    return result


def load_manual_reviews(
    path: Path, day: str
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    payload = load_json(path)
    if payload.get("version") != 1:
        raise ValueError(f"unsupported manual review version: {path}")

    def decisions_for(key: str) -> dict[str, dict[str, Any]]:
        rows = payload.get(key, {}).get(day, {})
        if not isinstance(rows, dict):
            raise ValueError(f"invalid {key} for {day}: {path}")
        result: dict[str, dict[str, Any]] = {}
        for raw_code, decision in rows.items():
            code = normalize_code(raw_code)
            if not code or not isinstance(decision, dict):
                raise ValueError(f"invalid manual review row: {day} {raw_code}")
            result[code] = decision
        return result

    additions = payload.get("stock_additions", {}).get(day, [])
    if not isinstance(additions, list):
        raise ValueError(f"invalid stock_additions for {day}: {path}")
    for addition in additions:
        if not isinstance(addition, dict):
            raise ValueError(f"invalid stock addition: {day} {addition!r}")
        code = normalize_code(addition.get("code", ""))
        name = str(addition.get("name", "")).strip()
        theme = str(addition.get("theme", "")).strip()
        if not code or not name or not theme:
            raise ValueError(f"incomplete stock addition: {day} {addition!r}")
    return decisions_for("fallback_decisions"), additions


def detect_header_bands(image: np.ndarray) -> list[tuple[int, int]]:
    """Detect the gold title bars used by the official poster template."""
    height, width = image.shape[:2]
    x0 = max(0, int(width * 0.025))
    x1 = min(width, int(width * 0.975))
    rgb = image[:, x0:x1]
    mask = (
        (rgb[:, :, 0] > 220)
        & (rgb[:, :, 1] > 145)
        & (rgb[:, :, 1] < 248)
        & (rgb[:, :, 2] < 195)
    )
    density = mask.mean(axis=1)
    candidate_rows = np.where(density > 0.45)[0]

    segments: list[list[int]] = []
    for raw_y in candidate_rows:
        y = int(raw_y)
        if not segments or y > segments[-1][-1] + 3:
            segments.append([y])
        else:
            segments[-1].append(y)

    bands: list[tuple[int, int]] = []
    for segment in segments:
        start, end = segment[0], segment[-1]
        band_height = end - start + 1
        if 6 <= band_height <= 90 and start > int(height * 0.05):
            bands.append((start, end))
    return bands


def ocr_tiled(
    image: np.ndarray,
    *,
    min_score: float,
    tile_height: int,
    overlap: int,
) -> list[Detection]:
    engine = get_ocr_engine()
    height, width = image.shape[:2]
    if tile_height <= overlap * 2:
        raise ValueError("tile_height must be greater than twice overlap")

    stride = tile_height - overlap
    starts = list(range(0, height, stride))
    detections: list[Detection] = []
    for start in starts:
        end = min(height, start + tile_height)
        crop = image[start:end, 0:width]
        result, _ = engine(crop)
        if not result:
            continue
        top_guard = overlap / 2 if start > 0 else 0
        bottom_guard = (end - start) - overlap / 2 if end < height else end - start
        for box, raw_text, raw_score in result:
            score = float(raw_score)
            text = str(raw_text).strip()
            if score < min_score or not text:
                continue
            local_x = (float(box[0][0]) + float(box[2][0])) / 2
            local_y = (float(box[0][1]) + float(box[2][1])) / 2
            if not (top_guard <= local_y <= bottom_guard):
                continue
            detections.append(
                Detection(x=local_x, y=local_y + start, text=text, score=score)
            )
    return detections


def clean_title(raw_text: str) -> str:
    text = str(raw_text).strip().replace("|", "")
    text = re.sub(r"^[^\u4e00-\u9fffA-Za-z]+", "", text)
    text = TITLE_SPLIT_RE.split(text, maxsplit=1)[0]
    return text.strip(" -—_/｜")


def title_for_band(
    detections: list[Detection], band: tuple[int, int], rank: int
) -> tuple[str, str | None]:
    start, end = band
    candidates = [
        det for det in detections if start - 8 <= det.y <= end + 8
    ]
    candidates.sort(key=lambda det: det.x)
    combined = " ".join(det.text for det in candidates)
    title = clean_title(combined)
    has_chinese = any("\u4e00" <= char <= "\u9fff" for char in title)
    is_market_acronym = bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9+./-]{1,15}", title))
    if title and (has_chinese or is_market_acronym):
        return title, None
    return f"未识别分组{rank}", f"第{rank}组标题无法识别: {combined!r}"


def cluster_rows(detections: list[Detection], tolerance: float = 13.0) -> list[list[Detection]]:
    rows: list[list[Detection]] = []
    centers: list[float] = []
    for detection in sorted(detections, key=lambda det: (det.y, det.x)):
        best_index = -1
        best_distance = tolerance + 1
        for index, center in enumerate(centers):
            distance = abs(detection.y - center)
            if distance <= tolerance and distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index < 0:
            rows.append([detection])
            centers.append(detection.y)
        else:
            rows[best_index].append(detection)
            centers[best_index] = sum(item.y for item in rows[best_index]) / len(
                rows[best_index]
            )
    for row in rows:
        row.sort(key=lambda det: det.x)
    return rows


def row_text(row: list[Detection]) -> str:
    return " ".join(det.text for det in row).strip()


def extracted_name_candidate(row: list[Detection], code: str | None) -> str:
    code_x: float | None = None
    if code:
        for det in row:
            token = normalize_text(det.text)
            if code in token:
                code_x = det.x
                attached_name = re.search(
                    rf"{re.escape(code)}([*A-Za-z\u4e00-\u9fff]{{2,12}})", token
                )
                if attached_name:
                    return attached_name.group(1)
                break
    for det in row:
        token = normalize_text(det.text)
        if not token or CODE_RE.search(token) or TIME_TOKEN_RE.match(token):
            continue
        if BOARD_TOKEN_RE.match(token) or "涨停" in token:
            continue
        if code_x is not None and not (code_x < det.x < code_x + 300):
            continue
        if 2 <= len(token) <= 12 and any("\u4e00" <= char <= "\u9fff" for char in token):
            return token
    return ""


def hamming_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right))
    return sum(a != b for a, b in zip(left, right))


def resolve_stock(
    row: list[Detection], stock_map: dict[str, str]
) -> tuple[ParsedStock | None, str | None]:
    combined = row_text(row)
    compact = normalize_text(combined)
    raw_codes = CODE_RE.findall(compact)

    direct_codes = [code for code in raw_codes if code in stock_map]
    if len(set(direct_codes)) == 1:
        code = direct_codes[0]
        return ParsedStock(code, stock_map[code], combined), None
    if len(set(direct_codes)) > 1:
        return None, f"同一OCR行出现多个股票代码: {combined}"

    matched_by_name = [
        code
        for code, name in stock_map.items()
        if normalize_text(name) and normalize_text(name) in compact
    ]
    if len(matched_by_name) == 1:
        code = matched_by_name[0]
        return ParsedStock(code, stock_map[code], combined), None

    if len(raw_codes) == 1:
        raw_code = raw_codes[0]
        ocr_name = extracted_name_candidate(row, raw_code)
        if ocr_name and re.search(r"退市整理|强制退市|退市", combined):
            return ParsedStock(raw_code, ocr_name, combined), None
        close_codes = [
            code for code in stock_map if hamming_distance(code, raw_code) == 1
        ]
        scored = [
            (
                SequenceMatcher(
                    None, normalize_text(ocr_name), normalize_text(stock_map[code])
                ).ratio(),
                code,
            )
            for code in close_codes
            if ocr_name
        ]
        scored.sort(reverse=True)
        if len(scored) == 1 and scored[0][0] >= 0.65:
            code = scored[0][1]
            return (
                ParsedStock(code, stock_map[code], combined),
                f"OCR代码按股票名校正: {raw_code}->{code}",
            )
        if scored and scored[0][0] >= 0.8 and (
            len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.2
        ):
            code = scored[0][1]
            return (
                ParsedStock(code, stock_map[code], combined),
                f"OCR代码按股票名校正: {raw_code}->{code}",
            )
        return None, f"图片股票未匹配当天涨停池: {combined}"

    return None, None


def parse_group_stocks(
    detections: list[Detection],
    start_y: int,
    end_y: int,
    stock_map: dict[str, str],
) -> tuple[list[ParsedStock], list[str]]:
    group_detections = [det for det in detections if start_y <= det.y < end_y]
    stocks: list[ParsedStock] = []
    issues: list[str] = []
    seen: set[str] = set()
    for row in cluster_rows(group_detections):
        stock, issue = resolve_stock(row, stock_map)
        if issue:
            issues.append(issue)
        if stock is None or stock.code in seen:
            continue
        seen.add(stock.code)
        stocks.append(stock)
    return stocks, issues


def reclassify_fallback_groups(
    groups: list[dict[str, Any]],
    manual_decisions: dict[str, dict[str, Any]],
    issues: list[str],
) -> list[dict[str, Any]]:
    explicit = [group for group in groups if not is_fallback_group(group["title"])]
    fallback = [group for group in groups if is_fallback_group(group["title"])]
    by_title = {group["title"]: group for group in explicit}

    for group in fallback:
        unresolved: list[ParsedStock] = []
        for stock in group["_parsed_stocks"]:
            decision = manual_decisions.get(stock.code)
            if decision is None:
                unresolved.append(stock)
                issues.append(
                    "其他组待人工审核: "
                    f"{stock.code} {stock.name} | {stock.event_text}"
                )
                continue
            theme = str(decision.get("theme", "")).strip()
            if not theme:
                raise ValueError(f"人工审核题材为空: {stock.code} {stock.name}")
            if theme not in by_title:
                new_group = {"title": theme, "_parsed_stocks": []}
                explicit.append(new_group)
                by_title[theme] = new_group
            by_title[theme]["_parsed_stocks"].append(stock)
        if unresolved:
            group["_parsed_stocks"] = unresolved
            explicit.append(group)

    for rank, group in enumerate(explicit, 1):
        group["rank"] = rank
    return explicit


def apply_manual_additions(
    groups: list[dict[str, Any]], additions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    existing_codes = {
        stock.code for group in groups for stock in group["_parsed_stocks"]
    }
    by_title = {group["title"]: group for group in groups}
    for addition in additions:
        code = normalize_code(addition["code"])
        if code in existing_codes:
            continue
        theme = str(addition["theme"]).strip()
        if theme not in by_title:
            new_group = {"title": theme, "_parsed_stocks": []}
            groups.append(new_group)
            by_title[theme] = new_group
        by_title[theme]["_parsed_stocks"].append(
            ParsedStock(
                code=code,
                name=str(addition["name"]).strip(),
                event_text=str(addition.get("event", "")).strip(),
            )
        )
        existing_codes.add(code)
    for rank, group in enumerate(groups, 1):
        group["rank"] = rank
    return groups


def validate_document(document: dict[str, Any]) -> None:
    groups = document.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("document has no groups")
    seen: set[str] = set()
    for expected_rank, group in enumerate(groups, 1):
        if group.get("rank") != expected_rank:
            raise ValueError(f"invalid group rank: {group!r}")
        if not str(group.get("title", "")).strip():
            raise ValueError(f"empty group title: rank {expected_rank}")
        for stock in group.get("stocks", []):
            code = str(stock.get("code", ""))
            name = str(stock.get("name", "")).strip()
            if not re.fullmatch(r"\d{6}", code) or not name:
                raise ValueError(f"invalid stock row: {stock!r}")
            if code in seen:
                raise ValueError(f"duplicate stock code in one day: {code}")
            seen.add(code)


def relative_source_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def process_image(path_text: str, config: dict[str, Any]) -> dict[str, Any]:
    image_path = Path(path_text)
    day = parse_image_day(image_path)
    stock_map = load_day_stock_map(Path(config["raw_root"]), day)
    fallback_reviews, stock_additions = load_manual_reviews(
        Path(config["manual_reviews_path"]), day
    )

    with Image.open(image_path) as opened:
        image = np.array(opened.convert("RGB"))
    bands = detect_header_bands(image)
    if not bands:
        raise ValueError(f"no title bands detected: {image_path}")

    detections = ocr_tiled(
        image,
        min_score=float(config["min_score"]),
        tile_height=int(config["tile_height"]),
        overlap=int(config["tile_overlap"]),
    )
    issues: list[str] = []
    groups: list[dict[str, Any]] = []

    for index, band in enumerate(bands):
        rank = index + 1
        title, title_issue = title_for_band(detections, band, rank)
        if title_issue:
            issues.append(title_issue)
        content_start = band[1] + 1
        content_end = bands[index + 1][0] if index + 1 < len(bands) else image.shape[0]
        stocks, stock_issues = parse_group_stocks(
            detections, content_start, content_end, stock_map
        )
        issues.extend(f"第{rank}组 {message}" for message in stock_issues)
        if not stocks:
            issues.append(f"第{rank}组未识别到股票: {title}")
        groups.append({"rank": rank, "title": title, "_parsed_stocks": stocks})

    groups = reclassify_fallback_groups(groups, fallback_reviews, issues)
    groups = apply_manual_additions(groups, stock_additions)

    recognized: set[str] = set()
    output_groups: list[dict[str, Any]] = []
    for rank, group in enumerate(groups, 1):
        stocks: list[dict[str, str]] = []
        for parsed in group.pop("_parsed_stocks"):
            if parsed.code in recognized:
                issues.append(f"重复股票已移除: {parsed.code} {parsed.name}")
                continue
            recognized.add(parsed.code)
            stocks.append({"code": parsed.code, "name": parsed.name})
        if stocks:
            output_groups.append(
                {"rank": len(output_groups) + 1, "title": group["title"], "stocks": stocks}
            )

    missing_codes = sorted(set(stock_map) - recognized)
    if missing_codes:
        preview = ", ".join(
            f"{code} {stock_map[code]}" for code in missing_codes[:30]
        )
        suffix = " ..." if len(missing_codes) > 30 else ""
        issues.append(f"当天涨停池未在图片分组中识别({len(missing_codes)}): {preview}{suffix}")

    document = {
        "date": day,
        "source": "tonghuashun_strong_wind",
        "source_image": relative_source_path(image_path),
        "groups": output_groups,
        "issues": list(dict.fromkeys(issues)),
    }
    validate_document(document)
    return document


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def valid_month(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise argparse.ArgumentTypeError("month must be YYYY-MM")
    date.fromisoformat(value + "-01")
    return value


def valid_day(value: str) -> str:
    date.fromisoformat(value)
    return value


def collect_images(args: argparse.Namespace) -> list[Path]:
    image_root = args.image_root.resolve()
    selected: dict[str, Path] = {}

    for month in args.month:
        for path in (image_root / month).glob("*.png"):
            if DATE_STEM_RE.fullmatch(path.stem):
                selected[path.stem] = path

    for day in args.date:
        stem = day.replace("-", "")
        path = image_root / day[:7] / f"{stem}.png"
        if path.exists():
            selected[stem] = path
        else:
            raise FileNotFoundError(f"image does not exist: {path}")

    if args.start or args.end or args.all:
        start = args.start or "0001-01-01"
        end = args.end or "9999-12-31"
        for path in image_root.glob("20??-??/*.png"):
            if not DATE_STEM_RE.fullmatch(path.stem):
                continue
            day = parse_image_day(path)
            if start <= day <= end:
                selected[path.stem] = path

    if not selected:
        raise ValueError("no images selected; use --month, --date, --start/--end, or --all")
    return [selected[key] for key in sorted(selected)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", action="append", default=[], type=valid_month)
    parser.add_argument("--date", action="append", default=[], type=valid_day)
    parser.add_argument("--start", type=valid_day)
    parser.add_argument("--end", type=valid_day)
    parser.add_argument("--all", action="store_true", help="process every dated PNG")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true", help="exit 2 when any issues remain")
    parser.add_argument("--min-score", type=float, default=0.35)
    parser.add_argument("--tile-height", type=int, default=1200)
    parser.add_argument("--tile-overlap", type=int, default=120)
    parser.add_argument("--image-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument(
        "--manual-reviews", type=Path, default=DEFAULT_MANUAL_REVIEWS
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if not args.manual_reviews.exists():
        raise SystemExit(f"manual review file does not exist: {args.manual_reviews}")
    images = collect_images(args)
    output_dir = args.output_dir.resolve()

    runnable: list[Path] = []
    for image in images:
        output = output_dir / f"{parse_image_day(image)}.json"
        if output.exists() and not args.overwrite:
            print(f"SKIP {output.name} (use --overwrite)")
        else:
            runnable.append(image)

    config = {
        "raw_root": str(args.raw_root.resolve()),
        "manual_reviews_path": str(args.manual_reviews.resolve()),
        "min_score": args.min_score,
        "tile_height": args.tile_height,
        "tile_overlap": args.tile_overlap,
    }
    results: list[dict[str, Any]] = []
    failures: list[str] = []

    if args.workers == 1:
        for image in runnable:
            try:
                results.append(process_image(str(image), config))
            except Exception as exc:  # report per-day failure and continue
                failures.append(f"{image.name}: {type(exc).__name__}: {exc}")
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(process_image, str(image), config): image
                for image in runnable
            }
            for future in as_completed(futures):
                image = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    failures.append(f"{image.name}: {type(exc).__name__}: {exc}")

    issue_count = 0
    for document in sorted(results, key=lambda item: item["date"]):
        issue_count += len(document["issues"])
        stock_count = sum(len(group["stocks"]) for group in document["groups"])
        if not args.dry_run:
            atomic_write_json(output_dir / f"{document['date']}.json", document)
        action = "CHECK" if args.dry_run else "WROTE"
        print(
            f"{action} {document['date']} groups={len(document['groups'])} "
            f"stocks={stock_count} issues={len(document['issues'])}"
        )

    for failure in failures:
        print(f"FAILED {failure}", file=sys.stderr)
    print(
        f"SUMMARY selected={len(images)} processed={len(results)} "
        f"failed={len(failures)} issues={issue_count}"
    )
    if failures:
        return 1
    if args.strict and issue_count:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
