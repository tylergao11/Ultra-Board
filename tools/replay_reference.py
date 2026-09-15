"""只为缺少开盘参考价的记录补同花顺分红配股日期。"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import re

from bs4 import BeautifulSoup

from replay_sources import DATA, OUT, CN_TZ, direct_session, reference_candidates
from ultraboard.kaipanla.query import _read, _write


def ex_reference(previous_close, plan):
    """按同花顺实施方案计算除权除息参考价。"""
    base = re.match(r"\s*(\d+(?:\.\d+)?)", plan or "")
    if not base or float(base.group(1)) <= 0:
        return None
    per = float(base.group(1))
    cash = sum(float(x) for x in re.findall(r"派\s*(\d+(?:\.\d+)?)\s*元", plan)) / per
    shares = sum(float(x) for x in re.findall(r"(?:送|转(?:增)?)\s*(\d+(?:\.\d+)?)\s*股", plan)) / per
    rights = re.search(r"配\s*(\d+(?:\.\d+)?)\s*股(?:配股价)?\s*(\d+(?:\.\d+)?)\s*元", plan)
    rights_ratio = float(rights.group(1)) / per if rights else 0
    rights_price = float(rights.group(2)) if rights else 0
    if not (cash or shares or rights_ratio):
        return None
    return round((previous_close - cash + rights_ratio * rights_price) / (1 + shares + rights_ratio), 2)


def fetch_actions(code, through):
    path = DATA / "ths" / "corporate_actions" / f"{code}.json"
    if path.exists():
        cached = _read(path)
        if cached.get("captured_at", "")[:10] >= through:
            return cached
    url = f"https://basic.10jqka.com.cn/{code}/bonus.html"
    response = direct_session().get(url, timeout=15)
    response.raise_for_status()
    response.encoding = "gbk"
    soup = BeautifulSoup(response.text, "html.parser")
    tables = [t for t in soup.select("table") if "A股除权除息日" in t.get_text()]
    if len(tables) != 1 or code not in response.text:
        raise ValueError("缺少分红表或股票编号，不能认定无除权")
    rows, ex_dates, years = [], set(), []
    for tr in tables[0].select("tr"):
        cells = [x.get_text(" ", strip=True) for x in tr.find_all("td", recursive=False)]
        if not cells:
            continue
        if len(cells) != 11 or not re.match(r"\d{4}", cells[0]):
            raise ValueError("分红表行结构变化")
        rows.append(cells)
        years.append(int(cells[0][:4]))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[6]):
            ex_dates.add(cells[6])
    if not rows:
        raise ValueError("分红表为空，保留缺口")
    rights_dates = []
    for td in soup.select("td"):
        if td.get_text(strip=True).startswith("除权日："):
            value = td.select_one("span")
            value = value.get_text(strip=True) if value else ""
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                rights_dates.append(value)
            elif value != "--":
                raise ValueError("配股除权日期结构变化")
    body = {"code": code, "source_url": url, "captured_at": datetime.now(CN_TZ).isoformat(),
            "dividend_rows": rows, "rights_ex_dates": rights_dates,
            "ex_dates": sorted(ex_dates | set(rights_dates)), "earliest_report_year": min(years),
            "latest_report_year": max(years)}
    _write(path, body)
    return body


def run_references(days):
    def needs_review(row):
        return (row.get("reference_candidate_source") == "dabanke"
                and row.get("reference_price") is not None and row.get("previous_trade_close") is not None
                and abs(row["reference_price"] - row["previous_trade_close"]) > 0.005)

    needed = set()
    for day in days:
        for row in _read(OUT / "prices" / f"{day}.json")["stocks"]:
            if row.get("open") and row.get("previous_trade_close") and (row.get("open_pct") is None or needs_review(row)):
                needed.add(row["code"])
    actions, errors = {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_actions, code, days[-1]): code for code in sorted(needed)}
        for i, future in enumerate(as_completed(futures), 1):
            code = futures[future]
            try:
                actions[code] = future.result()
            except Exception as exc:
                errors.append({"code": code, "error": str(exc)})
            if i % 50 == 0 or i == len(futures):
                print(f"除权日期 {i}/{len(futures)} 请求缺口{len(errors)}", flush=True)
    filled, corrected = 0, 0
    for day in days:
        path = OUT / "prices" / f"{day}.json"
        body, changed = _read(path), False
        for row in body["stocks"]:
            review = needs_review(row)
            if (row.get("open_pct") is not None and not review) or not row.get("open"):
                continue
            pct = row.get("close_change_pct")
            action = actions.get(row["code"])
            previous = row.get("previous_trade_date")
            ex_row = None
            if action:
                ex_row = next((x for x in action.get("dividend_rows", [])
                               if len(x) > 6 and x[6] == day), None)
            if ex_row and row.get("previous_trade_close") is not None:
                reference = ex_reference(row["previous_trade_close"], ex_row[4])
                if reference is not None:
                    row.update(reference_price=reference,
                               reference_status="calculated_from_ths_corporate_action",
                               reference_source_path=f"data/ths/corporate_actions/{row['code']}.json",
                               open_pct=round((row["open"] / reference - 1) * 100, 4))
                    changed = True
                    filled += 1
                    continue
            if pct is not None:
                candidates = reference_candidates(row["close"], pct)
                row["reference_candidates"] = candidates
                previous_close = row.get("previous_trade_close")
                if previous_close is not None and any(abs(previous_close - x) < 0.005001 for x in candidates):
                    candidates = [previous_close]
                if len(candidates) == 1:
                    row.update(reference_price=candidates[0],
                               reference_status="unique_cent_value_from_close_and_reported_change",
                               open_pct=round((row["open"] / candidates[0] - 1) * 100, 4))
                    changed = True
                    filled += 1
                    continue
            if not action or not previous or action["earliest_report_year"] > int(previous[:4]):
                continue
            if any(previous < d <= day for d in action["ex_dates"]):
                continue
            reference = row["previous_trade_close"]
            pct = row.get("close_change_pct")
            if pct is not None and abs((row["close"] / reference - 1) * 100 - float(pct)) > 0.005001:
                if row.get("reference_candidate_source") != "dabanke":
                    continue
                row.pop("close_change_pct", None)
                row.pop("reference_candidates", None)
            row.update(reference_price=reference,
                       reference_status="previous_close_no_ex_date_in_ths_actions",
                       reference_source_path=f"data/ths/corporate_actions/{row['code']}.json",
                       open_pct=round((row["open"] / reference - 1) * 100, 4))
            changed = True
            if review:
                corrected += 1
            else:
                filled += 1
        if changed:
            _write(path, body)
    _write(OUT / "reference_progress.json", {"requested_stocks": len(needed), "fetched_stocks": len(actions),
                                            "filled_rows": filled, "corrected_rows": corrected, "errors": errors})
    print(f"开盘参考价补回 {filled} 条，纠正 {corrected} 条", flush=True)
