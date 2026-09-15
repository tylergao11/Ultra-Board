"""行情补缺和本地价格索引；不使用行情网站的属性或催化。"""
from __future__ import annotations

import json
import re
import time
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from ultraboard.kaipanla.client import CN_TZ, KaipanlaClient
from ultraboard.kaipanla.query import _read, _write, _check_response
from ultraboard.kaipanla.backfill import is_bse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "replay"
_SESSIONS = threading.local()


def direct_session() -> requests.Session:
    if not hasattr(_SESSIONS, "value"):
        session = requests.Session()
        session.trust_env = False
        session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://stockpage.10jqka.com.cn/"})
        _SESSIONS.value = session
    return _SESSIONS.value


def stamp(day: str, text: str) -> int | None:
    if not re.fullmatch(r"\d{2}:\d{2}:\d{2}", text):
        return None
    return int(datetime.fromisoformat(day + "T" + text).replace(tzinfo=CN_TZ).timestamp())


def dabanke_market(day: str) -> dict:
    path = DATA / "dabanke" / "raw" / f"{day}.json"
    url = f"https://dabanke.com/index-{day.replace('-', '')}.html"
    if path.exists():
        raw = _read(path)
        if 'market_ref' in raw:
            resolved = (ROOT / raw['market_ref']).resolve()
            if not resolved.is_relative_to((OUT / 'market').resolve()):
                raise ValueError('行情映射路径越界')
            if resolved.exists():
                return _read(resolved)
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            response.encoding = 'utf-8'
            raw = {'date': day, 'url': url, 'captured_at': datetime.now(CN_TZ).isoformat(), 'html': response.text}
    else:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        response.encoding = "utf-8"
        raw = {"date": day, "url": url, "captured_at": datetime.now(CN_TZ).isoformat(), "html": response.text}
    soup = BeautifulSoup(raw["html"], "html.parser")
    title = soup.title.get_text() if soup.title else ""
    if day not in title:
        raise ValueError(f"打板客响应日期错误: {day}: {title}")
    stocks = {}
    for block in soup.select(".yzt-stock-row"):
        a = block.select_one("a.yzt-stock-name")
        change = block.select_one(".yzt-change-num")
        if not a or not change:
            continue
        match = re.search(r"gupiao-(\d{6})", a.get("href", ""))
        if not match:
            continue
        code = match[1]
        # 仅用状态标记，不读取 stock-reason-mini 或概念表。
        status = next((x.get_text(strip=True) for x in block.find_all("span", recursive=False)
                       if x.get_text(strip=True) in ("(成)", "(败)", "(炸)")), None)
        if status is None:
            raise ValueError(f"{day} {code} 缺少结果标记")
        stocks[code] = {"code": code, "name": a.get_text(strip=True),
                        "change_rate": float(change.get_text(strip=True)),
                        "closed_limit": status == "(成)", "failed_limit": status == "(炸)",
                        "provider": "dabanke", "source_url": url}
    detail_found = False
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        head = rows[0].get_text(" ", strip=True)
        if "首次封板" in head and "最后封板" in head:
            detail_found = True
            for row in rows[1:]:
                cells = [x.get_text(" ", strip=True) for x in row.find_all("td", recursive=False)]
                if len(cells) < 9 or not re.fullmatch(r"\d{6}", cells[0]):
                    continue
                code = cells[0]
                item = stocks.setdefault(code, {"code": code, "name": cells[1], "provider": "dabanke", "source_url": url})
                item.update(change_rate=float(cells[2]), first_limit_ts=stamp(day, cells[4]),
                            final_limit_ts=stamp(day, cells[5]), open_count=int(cells[6]),
                            boards=int(cells[8]), closed_limit=True, failed_limit=False)
        if "市场总览" in head and day in head:
            for row in rows[1:]:
                cells = row.find_all("td", recursive=False)
                if not cells:
                    continue
                label = cells[0].get_text(strip=True)
                if label not in ("一字板", "T字板"):
                    continue
                for a in row.select('a[href*="gupiao-"]'):
                    code = re.search(r"gupiao-(\d{6})", a["href"])[1]
                    if code in stocks:
                        stocks[code]["board_type"] = label
    if not detail_found or not stocks:
        raise ValueError(f"{day} 打板客缺少行情表")
    _write(path, {'date': day, 'url': url, 'captured_at': raw['captured_at'],
                  'market_ref': f'data/replay/market/{day}.json'})
    return {"date": day, "provider": "dabanke", "source_url": url,
            "captured_at": raw["captured_at"], "stocks": list(stocks.values())}


def apply_saved_ths_market(body: dict, day: str) -> None:
    """两个同花顺池各自独立复用，不要求同时存在才能作为主源。"""
    stocks = {r["code"]: r for r in body["stocks"]}
    for folder, provider, closed in (("limit_pool", "tonghuashun_limit_up_pool", True),
                                     ("open_limit_pool", "tonghuashun_open_limit_pool", False)):
        path = DATA / "ths" / folder / f"{day}.json"
        if not path.exists():
            continue
        saved = _read(path)
        if saved.get("date") != day or saved.get("count") != len(saved["stocks"]):
            raise ValueError("同花顺缓存日期或数量错误")
        for fact in saved["stocks"]:
            row = stocks.setdefault(fact["code"], {"code": fact["code"]})
            row.update({k: v for k, v in fact.items() if v is not None})
            row.update(provider=provider, closed_limit=closed, failed_limit=not closed,
                       source_path=str(path.relative_to(ROOT)))
            row.pop("source_url", None)
            row.pop("first_limit_time_source", None)
            if not closed:
                row.pop("final_limit_ts", None)
    body["stocks"] = list(stocks.values())


def align_closed_pool_to_kpl(body: dict, day: str) -> None:
    """开盘啦定义当日涨停池；打板客只补池内股票的行情字段。"""
    expected = {x["code"] for x in _read(DATA / "kaipanla" / "raw" / day / "zt_pool.json")["stocks"]}
    body["stocks"] = [x for x in body["stocks"]
                      if not x.get("closed_limit") or x["code"] in expected]
    actual = {x["code"] for x in body["stocks"] if x.get("closed_limit")}
    body["missing_kpl_limit_codes"] = sorted(expected - actual)


def market_day(day: str) -> dict:
    target = OUT / "market" / f"{day}.json"
    if target.exists():
        body = _read(target)
        if body["date"] != day:
            raise ValueError("行情缓存日期错误")
        apply_saved_ths_market(body, day)
        missing = set(body.get("missing_kpl_limit_codes", []))
        if missing:
            supplement = dabanke_market(day)
            present = {x["code"] for x in body["stocks"]}
            additions = [x for x in supplement["stocks"] if x["code"] in missing and x["closed_limit"] and x["code"] not in present]
            body["stocks"].extend(additions)
            body["missing_kpl_limit_codes"] = sorted(missing - {x["code"] for x in additions})
        align_closed_pool_to_kpl(body, day)
        add_seal_actions(body)
        _write(target, body)
        return body
    pool = DATA / "ths" / "limit_pool" / f"{day}.json"
    failed = DATA / "ths" / "open_limit_pool" / f"{day}.json"
    if pool.exists() and failed.exists():
        a, b = _read(pool), _read(failed)
        for doc in (a, b):
            if doc["date"] != day or doc["count"] != len(doc["stocks"]):
                raise ValueError("同花顺已有缓存日期或数量错误")
        items = [{**x, "closed_limit": True, "failed_limit": False, "provider": "tonghuashun_limit_up_pool"} for x in a["stocks"]]
        items += [{**x, "closed_limit": False, "failed_limit": True, "provider": "tonghuashun_open_limit_pool"} for x in b["stocks"]]
        body = {"date": day, "provider": "tonghuashun_saved", "stocks": items,
                "source_paths": [str(p.relative_to(ROOT)) for p in (pool, failed)]}
    else:
        body = dabanke_market(day)
    apply_saved_ths_market(body, day)
    codes = [x["code"] for x in body["stocks"]]
    if len(codes) != len(set(codes)):
        raise ValueError(f"{day} 行情代码重复")
    align_closed_pool_to_kpl(body, day)
    add_seal_actions(body)
    _write(target, body)
    return body


def add_seal_actions(body: dict) -> None:
    """按用户要求只提供有无动作；空缺不记作否，不判定有效买点。"""
    for row in body["stocks"]:
        provenance = row.get("first_limit_time_source") or {}
        if provenance.get("action") == "HisDaBanList" and provenance.get("field") == "raw[6]":
            row["kaipanla_reported_limit_ts"] = row.pop("first_limit_ts", None)
            row["kaipanla_reported_limit_time_source"] = row.pop("first_limit_time_source")
            row["kaipanla_reported_limit_time_semantics"] = "not_verified_as_first_touch"
        closed, failed = row.get("closed_limit"), row.get("failed_limit")
        row["has_seal_action"] = True if closed or failed else (False if closed is False and failed is False else None)
        count = row.get("open_count")
        if row["has_seal_action"] is False:
            row["has_reseal"] = False
        elif isinstance(count, int) and count >= 0:
            row["has_reseal"] = count >= 2 or (count >= 1 and closed is True)
        else:
            row["has_reseal"] = None
        row["seal_action_basis"] = "source_limit_or_failed_limit_status"
        row["reseal_basis"] = "source_open_count_and_closing_status" if isinstance(count, int) else "missing_open_count"
        row["has_limit_attack"] = row["has_seal_action"]
        first = row.get("first_limit_ts")
        row["first_limit_attack_ts"] = first if row["has_limit_attack"] and first else None
        row["first_limit_attack_time"] = datetime.fromtimestamp(first, CN_TZ).strftime("%H:%M:%S") if first else None
        row["first_limit_attack_session"] = ("auction" if row["first_limit_attack_time"] < "09:30:00" else "continuous") if first else None
        row["first_limit_attack_basis"] = "source_first_limit_time" if first else ("missing_first_limit_time" if row["has_limit_attack"] else "no_limit_attack")
    body["action_schema"] = 2


def run_attack_times(days: list[str]) -> None:
    client = KaipanlaClient(DATA / "kaipanla", interval_min=0.5, interval_max=1.0)
    for i, day in enumerate(days, 1):
        path = OUT / "market" / f"{day}.json"
        body = market_day(day)
        missing = {x["code"] for x in body["stocks"] if x["has_limit_attack"] and not x.get("first_limit_ts")}
        if not missing:
            continue
        cache = DATA / "kaipanla" / "raw" / day / "failed_limit_history.json"
        if cache.exists():
            pages = _read(cache)["raw_pages"]
        else:
            pages, index = [], 0
            while True:
                page = client.history_failed_limits(day, index)
                _check_response(page, day, "day")
                rows = page.get("list")
                if not isinstance(rows, list):
                    raise ValueError(f"{day} 炸板池结构错误")
                pages.append(page)
                if len(rows) < 50:
                    break
                index += len(rows)
            _write(cache, {"date": day, "source": "kaipanla_history_failed_limits_w45", "raw_pages": pages})
        records = {}
        for page in pages:
            _check_response(page, day, "day")
            for row in page["list"]:
                code = str(row[0])
                if code in records or len(row) < 8:
                    raise ValueError(f"{day} 炸板池代码重复或结构错误")
                if datetime.fromtimestamp(int(row[6]), CN_TZ).date().isoformat() != day:
                    raise ValueError(f"{day} 首次进攻时间不属于请求日期")
                records[code] = row
        for row in body["stocks"]:
            if row["code"] in missing and row["code"] in records:
                raw = records[row["code"]]
                row["kaipanla_reported_limit_ts"] = int(raw[6])
                row["kaipanla_reported_limit_time_source"] = {"provider": "kaipanla", "action": "HisDaBanList", "version": "w45", "field": "raw[6]", "path": str(cache.relative_to(ROOT))}
                row["kaipanla_reported_limit_time_semantics"] = "not_verified_as_first_touch"
        add_seal_actions(body)
        _write(path, body)
        if i % 20 == 0 or i == len(days):
            print(f"首次进攻时间 {i}/{len(days)} {day}", flush=True)


def run_market(days: list[str]) -> None:
    errors = []
    previous_codes = {}
    for index, day in enumerate(days):
        previous_codes[day] = {x["code"] for x in _read(DATA / "kaipanla" / "raw" / days[index - 1] / "zt_pool.json")["stocks"]} if index else set()
    def one(day):
        try:
            body = market_day(day)
            missing = previous_codes[day] - {x["code"] for x in body["stocks"]}
            if missing:
                supplement = dabanke_market(day)
                body["stocks"].extend(x for x in supplement["stocks"] if x["code"] in missing)
                align_closed_pool_to_kpl(body, day)
                body["missing_previous_limit_codes"] = sorted(previous_codes[day] - {x["code"] for x in body["stocks"]})
                add_seal_actions(body)
                _write(OUT / "market" / f"{day}.json", body)
            return day, body, None
        except (requests.RequestException, ValueError, KeyError, OSError) as exc:
            return day, None, str(exc)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for i, (day, body, error) in enumerate(pool.map(one, days), 1):
            if error:
                errors.append({"date": day, "error": error})
            if i % 25 == 0 or i == len(days):
                print(f"行情 {i}/{len(days)} 缺口{len(errors)} {day}", flush=True)
    _write(OUT / "market_errors.json", {"errors": errors})


def fetch_year(task: tuple[str, int, str]) -> tuple[str, str | None]:
    code, year, required_through = task
    target = DATA / "ths" / "prices_unadjusted" / code / f"{year}.json"
    if target.exists():
        saved = _read(target)
        if saved.get("requested_through", "") >= required_through:
            return code, None
    url = f"https://d.10jqka.com.cn/v6/line/hs_{code}/00/{year}.js"
    try:
        response = direct_session().get(url, timeout=15)
        response.raise_for_status()
        text = response.text
        raw = json.loads(text[text.index("(") + 1:text.rindex(")")])
        bars, unavailable = {}, []
        for line in raw["data"].split(";"):
            if not line:
                continue
            r = line.split(",")
            day = datetime.strptime(r[0], "%Y%m%d").date().isoformat()
            if not day.startswith(str(year)) or day in bars:
                raise ValueError("价格年份或日期重复")
            if any(not value.strip() for value in r[1:5]):
                unavailable.append(day)
                continue
            values = [float(x) for x in r[1:5]]
            if min(values) <= 0 or max(values[0], values[3]) > values[1] or min(values[0], values[3]) < values[2]:
                raise ValueError("OHLC不合法")
            bars[day] = {"open": values[0], "close": values[3]}
        if not bars:
            raise ValueError("价格为空")
        _write(target, {"code": code, "year": year, "source_url": url, "adjustment": "none",
                        "requested_through": required_through, "captured_at": datetime.now(CN_TZ).isoformat(),
                        "raw_response": raw, "bars": bars, "source_empty_price_dates": unavailable})
        return code, None
    except (requests.RequestException, ValueError, KeyError) as exc:
        return code, f"{year}: {exc}"


def price_requirements(days: list[str]) -> dict[str, set[str]]:
    needed = {}
    previous = set()
    for day in days:
        pool_path = DATA / "kaipanla" / "raw" / day / "zt_pool.json"
        current = {x["code"] for x in _read(pool_path)["stocks"]} if pool_path.exists() else set()
        market_path = OUT / "market" / f"{day}.json"
        market = {x["code"] for x in _read(market_path)["stocks"]
                  if not is_bse(x["code"]) and not re.match(r"\*?ST", x.get("name", "").upper())} if market_path.exists() else set()
        for code in current | previous | market:
            needed.setdefault(code, set()).add(day)
        previous = current
    return needed


def reference_candidates(close: float, pct: float) -> list[float]:
    """保留来源实际给出的百分比精度；两位显示值不能按四位反算。"""
    decimals = len(str(pct).partition(".")[2])
    tolerance = 0.5 * 10 ** -max(2, decimals)
    low = close / (1 + (float(pct) + tolerance) / 100)
    high = close / (1 + (float(pct) - tolerance) / 100)
    return [n / 100 for n in range(math.ceil(low * 100 - 1e-9), math.floor(high * 100 + 1e-9) + 1)
            if abs((close / (n / 100) - 1) * 100 - float(pct)) < tolerance + 1e-9]


def run_prices(days: list[str], fetch: bool = True) -> None:
    needed = price_requirements(days)
    tasks = []
    for code, dates in needed.items():
        for year in sorted({int(d[:4]) for d in dates}):
            tasks.append((code, year, max(d for d in dates if d.startswith(str(year)))))
    errors = []
    if fetch:
        with ThreadPoolExecutor(max_workers=4) as executor:
            for i, (code, error) in enumerate(executor.map(fetch_year, tasks), 1):
                if error:
                    errors.append({"code": code, "error": error})
                if i % 100 == 0 or i == len(tasks):
                    print(f"价格 {i}/{len(tasks)} 缺口{len(errors)}", flush=True)
        _write(OUT / "price_errors.json", {"errors": errors})
    # 本地日查询只加载所需字段；收盘涨幅可提供除权日参考价的候选值。
    all_bars = {}
    for code in needed:
        all_bars[code] = {}
        legacy_path = DATA / "price_checks" / "bars_dec24" / f"{code}.json"
        if legacy_path.exists():
            # 原采集代码已确认使用腾讯 day 未复权结果；仅复用已下载数据，不另行换源采集。
            for day, bar in _read(legacy_path).items():
                all_bars[code][day] = {"open": bar["open"], "close": bar["close"],
                                       "source": "tencent_saved_unadjusted",
                                       "source_path": str(legacy_path.relative_to(ROOT))}
        for path in (DATA / "ths" / "prices_unadjusted" / code).glob("*.json"):
            all_bars[code].update(_read(path)["bars"])
        for path in (DATA / "price_checks" / "missing_unadjusted" / code).glob("*.json"):
            for day, bar in _read(path)["bars"].items():
                all_bars[code].setdefault(day, {**bar, "source": "tencent_unadjusted_gap_fill", "source_path": str(path.relative_to(ROOT))})
    by_day = {}
    for code, dates in needed.items():
        bars = all_bars[code]
        sorted_days = sorted(bars)
        previous = {d: sorted_days[i - 1] for i, d in enumerate(sorted_days) if i}
        for day in dates:
            row = {"code": code, "date": day, "source": "tonghuashun_unadjusted", **bars.get(day, {})}
            if day in previous:
                row["previous_trade_close"] = bars[previous[day]]["close"]
                row["previous_trade_date"] = previous[day]
                row["open_pct_previous_close"] = round((row["open"] / row["previous_trade_close"] - 1) * 100, 4)
            row["reference_status"] = "not_verified"
            by_day.setdefault(day, []).append(row)
    for day, stocks in by_day.items():
        market_path = OUT / "market" / f"{day}.json"
        facts = {x["code"]: x for x in _read(market_path)["stocks"]} if market_path.exists() else {}
        for row in stocks:
            fact = facts.get(row["code"], {})
            pct = fact.get("change_rate")
            if "close" in row and pct is not None and float(pct) > -100:
                row["close_change_pct"] = pct
                # 以显示涨幅的舍入区间求全部分币参考价，不把四舍五入后的单个估值冒充精确值。
                candidates = reference_candidates(row["close"], pct)
                row["reference_candidates"] = candidates
                row["reference_candidate_source"] = fact.get("provider")
                same_close = fact.get("price") is None or abs(float(fact["price"]) - row["close"]) < 0.005
                if len(candidates) == 1 and same_close:
                    row["reference_price"] = candidates[0]
                    row["reference_status"] = "unique_cent_value_from_close_and_reported_change"
                    row["open_pct"] = round((row["open"] / candidates[0] - 1) * 100, 4)
            if "open" not in row:
                row["missing"] = "source_has_no_price_for_requested_day"
        apply_trading_status(day, stocks)
        _write(OUT / "prices" / f"{day}.json", {"date": day, "stocks": sorted(stocks, key=lambda x: x["code"])})


def apply_trading_status(day: str, stocks: list[dict]) -> None:
    path = OUT / "trading_status" / f"{day}.json"
    if not path.exists():
        return
    records = {x["code"]: x for x in _read(path)["stocks"]}
    for row in stocks:
        status = records.get(row["code"])
        if status and status.get("status") == "suspended" and status.get("source_url"):
            if row.get("open") is not None:
                raise ValueError(f"{day} {row['code']} 停牌记录与开盘价矛盾")
            row["trading_status"] = status
            row["reference_status"] = "not_applicable_suspended"
            row.pop("missing", None)


def run_price_gaps(days: list[str]) -> None:
    """只补统一日索引中实际缺失的价格，不重采已有事实。"""
    needed = price_requirements(days)
    missing = {}
    for day in days:
        path = OUT / "prices" / f"{day}.json"
        if not path.exists():
            raise ValueError("先运行 prices 或 index-prices 生成实际缺口")
        for row in _read(path)["stocks"]:
            if row.get("open") is None or row.get("close") is None:
                missing.setdefault((row["code"], int(day[:4])), set()).add(day)
    errors = []
    def one(item):
        (code, year), dates = item
        target = DATA / "price_checks" / "missing_unadjusted" / code / f"{year}.json"
        if target.exists():
            saved = _read(target)
            if set(dates) <= set(saved.get("requested_dates", [])):
                return None
        sym = ("sh" if code.startswith("6") else "sz") + code
        start = min(dates)
        # 多取前一段交易记录，供首个目标日的前收盘价使用。
        from datetime import date, timedelta
        start = (date.fromisoformat(start) - timedelta(days=15)).isoformat()
        end = max(dates)
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        params = {"param": f"{sym},day,{start},{end},640,"}
        try:
            response = direct_session().get(url, params=params, timeout=15)
            response.raise_for_status()
            raw = response.json()
            if raw.get("code") != 0:
                raise ValueError("来源返回错误码")
            rows = raw.get("data", {}).get(sym, {}).get("day", [])
            if not rows:
                raise ValueError("未复权 day 数据为空，不能用 qfqday 替代")
            bars = {}
            for row in rows:
                d = row[0]
                date.fromisoformat(d)
                if not start <= d <= end or d in bars:
                    raise ValueError("返回日期范围或唯一性错误")
                opening, close, high, low = map(float, row[1:5])
                if min(opening, close, high, low) <= 0 or max(opening, close) > high or min(opening, close) < low:
                    raise ValueError("价格结构错误")
                bars[d] = {"open": opening, "close": close}
            _write(target, {"code": code, "year": year, "source": "tencent_unadjusted_gap_fill",
                            "url": url, "params": params, "requested_dates": sorted(dates),
                            "captured_at": datetime.now(CN_TZ).isoformat(), "raw_response": raw, "bars": bars})
            return None
        except (requests.RequestException, ValueError, KeyError) as exc:
            return {"code": code, "year": year, "error": str(exc)}
    with ThreadPoolExecutor(max_workers=4) as executor:
        for result in executor.map(one, missing.items()):
            if result:
                errors.append(result)
    _write(OUT / "price_gap_errors.json", {"requested_code_years": len(missing), "errors": errors})
    print("价格缺项补采", len(missing), "失败", len(errors), flush=True)
    run_prices(days, fetch=False)
