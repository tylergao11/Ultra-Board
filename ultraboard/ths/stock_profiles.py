# -*- coding: utf-8 -*-
"""采集最近交易日涨停/炸板股票的同花顺 F10 完整概念与地域快照。

同花顺 F10 只提供当前页面，不提供指定历史日的概念成员快照。因此本模块
只允许目标日等于接口当前最后交易日，并明确记录抓取时间；不得拿今天的
概念页伪造过去某一天当时已经公开的题材归属。

用法：

  python -m ultraboard.ths.stock_profiles 2026-09-04
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup, Tag

from ultraboard.ths.limit_pool import load_day as load_limit_day
from ultraboard.ths.open_limit_pool import load_day as load_open_limit_day


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "data" / "ths" / "stock_profiles"
F10_BASE = "https://basic.10jqka.com.cn"
TIME_ENDPOINT = "https://d.10jqka.com.cn/v6/time/hs_{code}/last.js"
CN_TZ = timezone(timedelta(hours=8))
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SPACE_RE = re.compile(r"\s+")
QUANTITY_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)(万|亿)?$")


def output_path(day: str) -> Path:
    return OUTPUT_DIR / f"{day}.json"


def _new_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": "", "https": ""}
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        }
    )
    return session


def _code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() and len(text) <= 6 else ""


def _clean_text(value: Any) -> str:
    return SPACE_RE.sub(" ", str(value or "").replace("\xa0", " ")).strip()


def _response_text(response: requests.Response, label: str) -> str:
    response.raise_for_status()
    raw_head = response.content[:2048].lower()
    response.encoding = "gbk" if b"charset=gbk" in raw_head else response.apparent_encoding
    text = response.text
    if "同花顺金融服务网" not in text:
        raise RuntimeError(f"同花顺 F10 页面合同异常: {label}")
    return text


def _page_field(soup: BeautifulSoup, label: str) -> str:
    normalized_label = label.rstrip("：:")
    for strong in soup.find_all("strong"):
        current = _clean_text(strong.get_text(" ", strip=True)).rstrip("：:")
        if current != normalized_label:
            continue
        sibling = strong.find_next_sibling("span")
        if isinstance(sibling, Tag):
            return _clean_text(sibling.get_text(" ", strip=True))
    return ""


def _row_explanation(row: Tag) -> str:
    sibling = row.find_next_sibling("tr")
    if isinstance(sibling, Tag) and "extend_content" in (sibling.get("class") or []):
        return _clean_text(sibling.get_text(" ", strip=True))
    wider = row.find("td", class_="wider")
    return _clean_text(wider.get_text(" ", strip=True)) if isinstance(wider, Tag) else ""


def _share_quantity(value: str) -> int | None:
    text = _clean_text(value).replace(",", "")
    if text in {"", "-", "--"}:
        return None
    match = QUANTITY_RE.fullmatch(text)
    if match is None:
        raise RuntimeError(f"同花顺股本数量格式异常: {value!r}")
    multiplier = {None: 1, "万": 10_000, "亿": 100_000_000}[match.group(2)]
    return round(float(match.group(1)) * multiplier)


def _share_structure(soup: BeautifulSoup, target_day: str) -> dict[str, Any]:
    section = soup.find(id="stockcapit")
    table = section.find("table") if isinstance(section, Tag) else None
    if not isinstance(table, Tag):
        raise RuntimeError("同花顺股本页缺少总股本结构表")
    head = table.select_one("thead > tr")
    if not isinstance(head, Tag):
        raise RuntimeError("同花顺股本页缺少报告日期")
    headings = [_clean_text(cell.get_text(" ", strip=True)) for cell in head.find_all("th")]
    if len(headings) < 2:
        raise RuntimeError("同花顺股本页报告日期异常")
    target_date = date.fromisoformat(target_day)
    dated_columns = [
        (date.fromisoformat(value), index)
        for index, value in enumerate(headings[1:])
    ]
    eligible_columns = [item for item in dated_columns if item[0] <= target_date]
    if not eligible_columns:
        raise RuntimeError(f"同花顺股本页没有不晚于目标日的报告列: {target_day}")
    report_day, value_index = max(eligible_columns, key=lambda item: item[0])
    report_date = report_day.isoformat()

    labels = {
        "总股本(股)": "total_shares",
        "A股总股本(股)": "a_share_total",
        "流通A股(股)": "circulating_a_shares",
        "限售A股(股)": "restricted_a_shares",
    }
    values: dict[str, dict[str, Any]] = {}
    for row in table.select("tbody > tr"):
        header = row.find("th")
        cells = row.find_all("td", recursive=False)
        if not isinstance(header, Tag) or not cells:
            continue
        label = _clean_text(header.get_text(" ", strip=True))
        field = labels.get(label)
        if field is None:
            continue
        if value_index >= len(cells):
            raise RuntimeError(f"同花顺股本页 {label} 缺少 {report_date} 列")
        raw = _clean_text(cells[value_index].get_text(" ", strip=True))
        values[field] = {"source_text": raw, "approximate_shares": _share_quantity(raw)}
    if set(values) != set(labels.values()):
        raise RuntimeError(
            f"同花顺股本页字段不完整: missing={sorted(set(labels.values()) - set(values))}"
        )
    return {"report_date": report_date, **values}


def _concept_rows(
    soup: BeautifulSoup,
    *,
    section_id: str,
    kind: str,
    cell_class: str,
    optional: bool = False,
) -> list[dict[str, Any]]:
    section = soup.find(id=section_id)
    if not isinstance(section, Tag):
        if optional:
            return []
        raise RuntimeError(f"同花顺概念页缺少 #{section_id}")
    table = section.find("table", class_="gnContent")
    if not isinstance(table, Tag):
        if optional:
            return []
        raise RuntimeError(f"同花顺概念页 #{section_id} 缺少概念表")

    result: list[dict[str, Any]] = []
    for row in table.select("tbody > tr"):
        if "extend_content" in (row.get("class") or []):
            continue
        cell = row.find("td", class_=cell_class)
        if not isinstance(cell, Tag):
            continue
        name = _clean_text(cell.get_text(" ", strip=True))
        if not name:
            raise RuntimeError(f"同花顺概念页 #{section_id} 出现空概念名")
        source_id = _clean_text(cell.get("cid") or cell.get("clid")) or None
        result.append(
            {
                "name": name,
                "kind": kind,
                "source_id": source_id,
                "explanation": _row_explanation(row) or None,
            }
        )
    return result


def _parse_jsonp(text: str, label: str) -> dict[str, Any]:
    left = text.find("(")
    right = text.rfind(")")
    if left < 0 or right <= left:
        raise RuntimeError(f"同花顺分时响应不是合法 JSONP: {label}")
    body = json.loads(text[left + 1 : right])
    if not isinstance(body, dict):
        raise RuntimeError(f"同花顺分时响应不是对象: {label}")
    return body


def latest_market_day(code: str) -> str:
    code = _code(code)
    if not code:
        raise ValueError("股票代码非法")
    session = _new_session()
    response = session.get(
        TIME_ENDPOINT.format(code=code),
        headers={"Referer": f"{F10_BASE}/{code}/"},
        timeout=20,
    )
    response.raise_for_status()
    body = _parse_jsonp(response.text, code)
    stock = body.get(f"hs_{code}")
    if not isinstance(stock, dict):
        raise RuntimeError(f"同花顺最后交易日响应缺少股票: {code}")
    compact = str(stock.get("date") or "")
    if not re.fullmatch(r"\d{8}", compact):
        raise RuntimeError(f"同花顺最后交易日异常: {code} {compact!r}")
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"


def _fetch_profile(stock: dict[str, str]) -> dict[str, Any]:
    code = stock["code"]
    expected_name = stock["name"]
    target_day = stock["target_day"]
    company_url = f"{F10_BASE}/{code}/company.html"
    concept_url = f"{F10_BASE}/{code}/concept.html"
    equity_url = f"{F10_BASE}/{code}/equity.html"
    session = _new_session()

    company_response = session.get(
        company_url,
        headers={"Referer": f"{F10_BASE}/{code}/"},
        timeout=20,
    )
    company_text = _response_text(company_response, f"{code} company")
    company_soup = BeautifulSoup(company_text, "html.parser")

    concept_response = session.get(
        concept_url,
        headers={"Referer": f"{F10_BASE}/{code}/"},
        timeout=20,
    )
    concept_text = _response_text(concept_response, f"{code} concept")
    concept_soup = BeautifulSoup(concept_text, "html.parser")
    stock_name_input = concept_soup.find(id="stockName")
    page_name = (
        _clean_text(stock_name_input.get("value"))
        if isinstance(stock_name_input, Tag)
        else ""
    )
    if page_name != expected_name:
        raise RuntimeError(
            f"同花顺 F10 名称不一致: {code} expected={expected_name!r} page={page_name!r}"
        )

    equity_response = session.get(
        equity_url,
        headers={"Referer": f"{F10_BASE}/{code}/"},
        timeout=20,
    )
    equity_text = _response_text(equity_response, f"{code} equity")
    equity_soup = BeautifulSoup(equity_text, "html.parser")
    share_structure = _share_structure(equity_soup, target_day)

    region = _page_field(company_soup, "所属地域")
    company_name = _page_field(company_soup, "公司名称")
    shenwan_industry = _page_field(company_soup, "所属申万行业")
    office_address = _page_field(company_soup, "办公地址")
    if not region or not company_name or not shenwan_industry:
        raise RuntimeError(
            f"同花顺公司资料字段缺失: {code} "
            f"region={region!r} company={company_name!r} industry={shenwan_industry!r}"
        )

    regular = _concept_rows(
        concept_soup,
        section_id="concept",
        kind="regular",
        cell_class="gnName",
    )
    other = _concept_rows(
        concept_soup,
        section_id="other",
        kind="other",
        cell_class="gnStockList",
        optional=True,
    )
    concepts = regular + other
    concept_names = list(dict.fromkeys(item["name"] for item in concepts))
    if len(concept_names) != len(concepts):
        raise RuntimeError(f"同花顺概念页存在重复概念: {code}")

    market_input = concept_soup.find(id="marketId")
    market_id = (
        _clean_text(market_input.get("value"))
        if isinstance(market_input, Tag)
        else ""
    )
    if not market_id:
        raise RuntimeError(f"同花顺概念页缺少 marketId: {code}")
    key_points_url = f"{F10_BASE}/fuyao/f10_stock_index/concept/v1/theme_key_points"
    key_response = session.get(
        key_points_url,
        params={"subject": f"{market_id}-{code}"},
        headers={"Referer": concept_url, "Accept": "application/json, */*"},
        timeout=20,
    )
    key_response.raise_for_status()
    key_body = key_response.json()
    if key_body.get("status_code") != 0 or not isinstance(key_body.get("data"), list):
        raise RuntimeError(f"同花顺题材要点接口异常: {code}")
    key_points = []
    for item in key_body["data"]:
        if not isinstance(item, dict):
            raise RuntimeError(f"同花顺题材要点出现非对象: {code}")
        title = _clean_text(item.get("title"))
        content = _clean_text(item.get("content"))
        update_date = _clean_text(item.get("update_date")) or None
        if not title or not content:
            raise RuntimeError(f"同花顺题材要点为空: {code}")
        if update_date is not None:
            date.fromisoformat(update_date)
        key_points.append(
            {"title": title, "content": content, "update_date": update_date}
        )

    return {
        "code": code,
        "name": expected_name,
        "company_name": company_name,
        "region": region,
        "shenwan_industry": shenwan_industry,
        "office_address": office_address or None,
        "share_structure": share_structure,
        "concept_names": concept_names,
        "concepts": concepts,
        "theme_key_points": key_points,
        "source_market_id": market_id,
        "source_hashes": {
            "company_html_sha256": hashlib.sha256(company_response.content).hexdigest(),
            "concept_html_sha256": hashlib.sha256(concept_response.content).hexdigest(),
            "equity_html_sha256": hashlib.sha256(equity_response.content).hexdigest(),
            "theme_key_points_sha256": hashlib.sha256(key_response.content).hexdigest(),
        },
    }


def _stock_universe(day: str) -> list[dict[str, str]]:
    limit_payload = load_limit_day(day)
    if limit_payload is None:
        raise FileNotFoundError(f"缺少同花顺涨停池: {day}")
    open_payload = load_open_limit_day(day)
    rows = list(limit_payload.get("stocks") or [])
    if open_payload is not None:
        rows.extend(open_payload.get("stocks") or [])

    by_code: dict[str, str] = {}
    for row in rows:
        code = _code(row.get("code"))
        name = _clean_text(row.get("name"))
        if not code or not name:
            raise RuntimeError(f"{day} 股票资料候选代码或名称异常")
        existing = by_code.get(code)
        if existing is not None and existing != name:
            raise RuntimeError(f"{day} 同代码名称冲突: {code} {existing!r} {name!r}")
        by_code[code] = name
    return [{"code": code, "name": by_code[code]} for code in sorted(by_code)]


def fetch_day(
    day_value: str,
    *,
    stocks: Iterable[dict[str, Any]] | None = None,
    workers: int = 6,
) -> dict[str, Any]:
    day = date.fromisoformat(day_value).isoformat()
    if workers < 1 or workers > 12:
        raise ValueError("workers 必须在 1 到 12 之间")
    raw_stocks = list(stocks) if stocks is not None else _stock_universe(day)
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in raw_stocks:
        code = _code(row.get("code"))
        name = _clean_text(row.get("name"))
        if not code or not name or code in seen:
            raise ValueError(f"股票资料抓取集合异常: {code!r} {name!r}")
        seen.add(code)
        normalized.append({"code": code, "name": name, "target_day": day})
    normalized.sort(key=lambda row: row["code"])
    if not normalized:
        raise ValueError("股票资料抓取集合为空")

    source_latest_day = latest_market_day(normalized[0]["code"])
    if source_latest_day != day:
        raise RuntimeError(
            "同花顺 F10 只有当前资料，禁止伪造历史题材快照: "
            f"requested={day}, source_latest={source_latest_day}"
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        profiles = list(executor.map(_fetch_profile, normalized))

    fetched_at = datetime.now(CN_TZ).isoformat(timespec="seconds")
    payload = {
        "schema_version": 1,
        "date": day,
        "information_cutoff": fetched_at,
        "source": {
            "provider": "tonghuashun_f10_current_snapshot",
            "company_url_template": f"{F10_BASE}/{{code}}/company.html",
            "concept_url_template": f"{F10_BASE}/{{code}}/concept.html",
            "equity_url_template": f"{F10_BASE}/{{code}}/equity.html",
            "theme_key_points_endpoint": (
                f"{F10_BASE}/fuyao/f10_stock_index/concept/v1/theme_key_points"
            ),
            "fetched_at": fetched_at,
            "source_latest_market_day": source_latest_day,
            "universe": "tonghuashun limit_up_pool union open_limit_pool",
            "temporal_contract": (
                "当前 F10 页面在 fetched_at 的快照；只允许采集接口最后交易日，"
                "不能回填为更早日期当时已公开的概念归属"
            ),
        },
        "count": len(profiles),
        "stocks": profiles,
    }
    validate_payload(payload, day, output_path(day))
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def validate_payload(payload: dict[str, Any], day: str, path: Path) -> None:
    source = payload.get("source") or {}
    rows = payload.get("stocks")
    if (
        payload.get("schema_version") != 1
        or payload.get("date") != day
        or source.get("provider") != "tonghuashun_f10_current_snapshot"
        or source.get("source_latest_market_day") != day
        or not isinstance(rows, list)
        or payload.get("count") != len(rows)
    ):
        raise ValueError(f"同花顺股票资料合同异常: {path}")
    datetime.fromisoformat(str(payload.get("information_cutoff") or ""))

    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"同花顺股票资料行不是对象: {path}")
        code = _code(row.get("code"))
        if not code or row.get("code") != code or code in seen:
            raise ValueError(f"同花顺股票资料代码异常或重复: {path} {code!r}")
        seen.add(code)
        for field in ("name", "company_name", "region", "shenwan_industry"):
            if not _clean_text(row.get(field)):
                raise ValueError(f"同花顺股票资料缺少 {field}: {path} {code}")
        concepts = row.get("concepts")
        names = row.get("concept_names")
        if not isinstance(concepts, list) or not isinstance(names, list):
            raise ValueError(f"同花顺概念字段异常: {path} {code}")
        expected_names: list[str] = []
        for concept in concepts:
            if (
                not isinstance(concept, dict)
                or not _clean_text(concept.get("name"))
                or concept.get("kind") not in {"regular", "other"}
            ):
                raise ValueError(f"同花顺概念记录异常: {path} {code}")
            expected_names.append(concept["name"])
        if names != list(dict.fromkeys(expected_names)) or len(names) != len(expected_names):
            raise ValueError(f"同花顺概念名称索引不闭合: {path} {code}")
        structure = row.get("share_structure")
        if not isinstance(structure, dict):
            raise ValueError(f"同花顺股本结构异常: {path} {code}")
        report_date = date.fromisoformat(str(structure.get("report_date") or ""))
        if report_date.isoformat() > day:
            raise ValueError(f"同花顺股本报告日期晚于目标日: {path} {code}")
        for field in (
            "total_shares",
            "a_share_total",
            "circulating_a_shares",
            "restricted_a_shares",
        ):
            value = structure.get(field)
            if not isinstance(value, dict) or not _clean_text(value.get("source_text")):
                raise ValueError(f"同花顺股本字段异常: {path} {code} {field}")
            shares = value.get("approximate_shares")
            if shares is not None and (
                isinstance(shares, bool) or not isinstance(shares, int) or shares < 0
            ):
                raise ValueError(f"同花顺股本数量异常: {path} {code} {field}")
        key_points = row.get("theme_key_points")
        if not isinstance(key_points, list):
            raise ValueError(f"同花顺题材要点异常: {path} {code}")
        for point in key_points:
            if (
                not isinstance(point, dict)
                or not _clean_text(point.get("title"))
                or not _clean_text(point.get("content"))
            ):
                raise ValueError(f"同花顺题材要点记录异常: {path} {code}")
            if point.get("update_date") is not None:
                date.fromisoformat(point["update_date"])


def load_day(
    day_value: str,
    *,
    fetch_missing: bool = False,
    force: bool = False,
    workers: int = 6,
) -> dict[str, Any] | None:
    day = date.fromisoformat(day_value).isoformat()
    path = output_path(day)
    if path.exists() and not force:
        payload = _read_json(path)
    elif fetch_missing or force:
        payload = fetch_day(day, workers=workers)
        _write_json_atomic(path, payload)
    else:
        return None
    validate_payload(payload, day, path)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("date", help="接口当前最后交易日 YYYY-MM-DD")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)
    day = date.fromisoformat(args.date).isoformat()
    existed = output_path(day).exists()
    payload = load_day(
        day,
        fetch_missing=True,
        force=args.force,
        workers=args.workers,
    )
    assert payload is not None
    print(
        f"{'WROTE' if args.force or not existed else 'CHECKED'} {day} "
        f"stocks={payload['count']} -> {output_path(day)}"
    )
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
