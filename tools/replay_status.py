"""仅为实际缺报价的股票日期补历史停牌状态。"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import re
from bs4 import BeautifulSoup

from replay_sources import DATA, OUT, CN_TZ, direct_session, apply_trading_status
from ultraboard.kaipanla.query import _read, _write


def suspension(day, code):
    path = DATA / "ths" / "suspensions" / day / f"{code}.json"
    if path.exists():
        saved = _read(path)
    else:
        url = "http://search.10jqka.com.cn/thsft/iFindService/StockCalendar/index/detail"
        response = direct_session().get(url, params={"code": code, "date": day},
                                        headers={"Referer": "https://data.10jqka.com.cn/tradetips/tfpts/"}, timeout=12)
        response.raise_for_status()
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        if "停牌记录" not in soup.get_text() or code not in soup.get_text():
            raise ValueError("同花顺未返回对应股票停牌记录页面")
        records = []
        for tr in soup.select("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td", recursive=False)]
            if not cells or not re.fullmatch(r"\d{6}", cells[0]):
                continue
            if len(cells) != 8 or cells[0] != code:
                raise ValueError("同花顺停牌表结构或代码错误")
            records.append({"code": cells[0], "suspended_from": cells[2],
                            "resumed_on": cells[3], "period": cells[4]})
        saved = {"date": day, "code": code, "source_url": response.url,
                 "provider": "tonghuashun_suspension_history",
                 "captured_at": datetime.now(CN_TZ).isoformat(), "raw_html": response.text,
                 "records": records}
        _write(path, saved)
    if saved["date"] != day or saved["code"] != code:
        raise ValueError("停牌缓存请求日期或代码错误")
    matches = []
    for row in saved["records"]:
        start, resume = row["suspended_from"], row["resumed_on"]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", start) or start > day + " 09:30":
            continue
        if resume and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", resume) and resume <= day + " 15:00":
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", resume) and "连续停牌" not in row["period"]:
            continue
        matches.append(row)
    if not matches:
        return None
    return {"code": code, "status": "suspended", "source_url": saved["source_url"],
            "provider": "tonghuashun_suspension_history",
            "source_path": str(path.relative_to(DATA.parent)),
            "suspended_from": min(r["suspended_from"] for r in matches),
            "suspension_records": matches}


def run_status(days):
    needed = []
    for day in days:
        path = OUT / "prices" / f"{day}.json"
        for row in _read(path)["stocks"]:
            if row.get("open") is None and (row.get("trading_status") or {}).get("provider") != "tonghuashun_suspension_history":
                needed.append((day, row["code"]))
    found, errors, unresolved = {}, [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(suspension, day, code): (day, code) for day, code in needed}
        for future in as_completed(jobs):
            day, code = jobs[future]
            try:
                status = future.result()
                if status:
                    found.setdefault(day, []).append(status)
                else:
                    unresolved.append({"date": day, "code": code})
            except Exception as exc:
                errors.append({"date": day, "code": code, "error": str(exc)})
    for day, rows in found.items():
        target = OUT / "trading_status" / f"{day}.json"
        existing = _read(target) if target.exists() else {"date": day, "stocks": []}
        merged = {r["code"]: r for r in existing["stocks"]}
        merged.update({r["code"]: r for r in rows})
        _write(target, {"date": day, "stocks": list(merged.values())})
        path = OUT / "prices" / f"{day}.json"
        prices = _read(path)
        apply_trading_status(day, prices["stocks"])
        _write(path, prices)
    count = sum(len(rows) for rows in found.values())
    _write(OUT / "status_progress.json", {"requested": len(needed), "suspended": count,
                                        "unresolved": unresolved, "errors": errors})
    print(f"停牌状态补齐 {count}/{len(needed)}，未确认{len(unresolved)}，请求失败{len(errors)}", flush=True)
