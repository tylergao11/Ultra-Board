"""复盘补缺入口。缓存优先，阶段可独立续跑，缺口不冒充完成。"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ultraboard.kaipanla.client import CN_TZ, KaipanlaClient
from ultraboard.kaipanla.client import HIS_URL
from ultraboard.kaipanla.backfill import pull_one_day
from ultraboard.kaipanla.query import _read, _write, _check_response, _ladder_rows, _member_snapshot
from ultraboard.kaipanla import membership_store

DATA = ROOT / "data"
KPL = DATA / "kaipanla"
RAW = KPL / "raw"
OUT = DATA / "replay"


def trading_days(start: str, end: str) -> list[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    holidays = set()
    for year in range(first.year, last.year + 1):
        doc = _read(DATA / "calendar" / f"{year}.json")
        if doc["year"] != year or not doc["source"].startswith("https://www.sse.com.cn/"):
            raise ValueError("交易日历来源或年份错误")
        holidays.update(doc["holiday_dates"])
    days = []
    while first <= last:
        if first.weekday() < 5 and first.isoformat() not in holidays:
            days.append(first.isoformat())
        first += timedelta(days=1)
    return days


def reason_rows(body: dict, day: str) -> list:
    _check_response(body, day, "date")
    groups = body.get("list")
    if not isinstance(groups, list) or not groups:
        raise ValueError("历史复盘为空")
    rows = [r for g in groups for r in g.get("StockList", [])]
    if not rows:
        raise ValueError("历史复盘没有股票原文")
    for row in rows:
        if len(row) < 18 or datetime.fromtimestamp(int(row[6]), CN_TZ).date().isoformat() != day:
            raise ValueError("历史复盘股票时间或结构错误")
    return rows


def run_kpl(days: list[str]) -> None:
    client = KaipanlaClient(KPL, interval_min=0.5, interval_max=1.0)
    for i, day in enumerate(days, 1):
        folder = RAW / day
        if not (folder / "zt_pool.json").exists():
            status, message = pull_one_day(client, date.fromisoformat(day), set())
            if status != "ok":
                raise RuntimeError(f"{day}: {status}: {message}")
            print("涨停池补齐", day, flush=True)
        path = folder / "limit_ladder.json"
        if not path.exists():
            body = client.limit_ladder(day)
            _ladder_rows(body, day)
            _write(path, body)
        path = folder / "history_limit_resumption.json"
        if not path.exists():
            body = client.history_limit_resumption(day)
            reason_rows(body, day)
            # 100个板块仍满页时不能假定已取完。
            if len(body["list"]) >= 100:
                raise RuntimeError(f"{day} 复盘满页，需要补齐分页")
            _write(path, body)
        if i % 20 == 0 or i == len(days):
            print(f"开盘啦 {i}/{len(days)} {day}", flush=True)


def import_members() -> int:
    count = 0
    for path in sorted((KPL / "research_attributes").rglob("*.json")):
        doc = _read(path)
        query = doc.get("query", {})
        day, plate = query.get("date"), query.get("plate_code")
        if not day or not plate or not doc.get("raw_response"):
            continue
        target = KPL / "plate_members" / day / f"{plate}.json"
        if target.exists() or membership_store.snapshot(day, plate) is not None:
            continue
        try:
            normalized = _member_snapshot(day, plate, [doc["raw_response"]])
        except (ValueError, RuntimeError, TypeError):
            continue
        normalized["captured_at"] = doc.get("captured_at")
        normalized["imported_from"] = str(path.relative_to(ROOT))
        membership_store.put(day, plate, normalized)
        count += 1
    print("复用完整成员快照", count, flush=True)
    return count


def member_plan(days: list[str]) -> list[tuple[str, str]]:
    """当日来源实际出现的细分及前一交易日；不抓未出现的全市场概念。"""
    needed = set()
    for index, day in enumerate(days):
        codes = set()
        pool_path = RAW / day / "zt_pool.json"
        if pool_path.exists():
            codes.update(str(x.get("sector_code", "")) for x in _read(pool_path)["stocks"])
        reason_path = RAW / day / "history_limit_resumption.json"
        if reason_path.exists():
            codes.update(str(x.get("ZSCode", "")) for x in _read(reason_path).get("list", []))
        for code in codes:
            if len(code) == 6 and code.isdigit():
                needed.add((day, code))
                if index:
                    needed.add((days[index - 1], code))
    return sorted(needed)


def run_members(days: list[str], attempts: int = 2) -> None:
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    import threading
    import_members()
    full_plan = member_plan(days)
    plan = []
    for day, plate in full_plan:
        member_path = KPL / "plate_members" / day / f"{plate}.json"
        breadth_path = OUT / "breadth" / day / f"{plate}.json"
        breadth_ready = membership_store.snapshot(day, plate) is not None
        if not breadth_ready and breadth_path.exists():
            try:
                breadth_ready = _read(breadth_path).get("limit_count") is not None
            except Exception:
                pass
        if (not member_path.exists() and membership_store.snapshot(day, plate) is None) or not breadth_ready:
            plan.append((day, plate))
    print("成员计划", len(plan), "已有", sum((KPL / "plate_members" / d / f"{p}.json").exists() for d, p in plan), flush=True)
    _write(OUT / "member_plan.json", {"start": days[0], "end": days[-1], "requests": plan,
                                    "scope": "daily source sector IDs with one previous trading day"})
    local = threading.local()

    def one(job):
        day, plate = job
        if not hasattr(local, "client"):
            local.client = KaipanlaClient(KPL, interval_min=0.5, interval_max=1.0)
        client = local.client
        target = KPL / "plate_members" / day / f"{plate}.json"
        compact = membership_store.snapshot(day, plate)
        if compact is not None:
            snapshot = compact
        elif target.exists():
            snapshot = _member_snapshot(day, plate, _read(target)["raw_pages"])
        else:
            pages, index = [], 0
            while True:
                for attempt in range(attempts):
                    try:
                        page = client.post(HIS_URL, {
                            "a": "ZhiShuStockList_W8", "c": "ZhiShuRanking", "Date": day,
                            "PlateID": plate, "Index": str(index), "st": "1000",
                            "old": "1", "Order": "1", "Type": "20",
                        })
                        _check_response(page, day, "Day")
                        break
                    except Exception:
                        if attempt + 1 == attempts:
                            raise
                rows = page.get("list") or []
                if not rows or int(page.get("Count", 0)) <= 0:
                    return {"date": day, "plate_id": plate, "error": "此日期/编号未返回成员，不能计零"}
                pages.append(page)
                index += len(rows)
                if index >= int(page["Count"]):
                    break
                if len(rows) != 1000:
                    return {"date": day, "plate_id": plate, "error": "分页提前结束"}
            snapshot = _member_snapshot(day, plate, pages)
            snapshot["request"] = {"Type": "20", "st": "1000"}
            membership_store.put(day, plate, snapshot)
        pool = {r["code"]: r for r in _read(RAW / day / "zt_pool.json")["stocks"]}
        matched = [pool[m["code"]] for m in snapshot["members"] if m["code"] in pool]
        mismatched = [m["code"] for m in snapshot["members"] if m["code"] in pool
                      and m.get("price") is not None and pool[m["code"]].get("price") is not None
                      and abs(float(m["price"]) - float(pool[m["code"]]["price"])) > 0.005]
        # 数量是成员关系与涨停池的派生值，查询时计算，不重复保存板块文件。
        return {"date": day, "plate_id": plate, "error": "成员价格与涨停池矛盾", "codes": mismatched} if mismatched else None

    jobs = iter(plan)
    executor = ThreadPoolExecutor(max_workers=4)
    pending, errors, completed = {}, [], 0
    try:
        for _ in range(4):
            job = next(jobs, None)
            if job:
                pending[executor.submit(one, job)] = job
        while pending:
            ready, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in ready:
                job = pending.pop(future)
                try:
                    error = future.result()
                except Exception as exc:
                    error = {"date": job[0], "plate_id": job[1], "error": repr(exc)}
                completed += 1
                if error:
                    errors.append(error)
                if completed % 50 == 0 or completed == len(plan):
                    print(f"成员 {completed}/{len(plan)} 缺口{len(errors)} {job[0]}", flush=True)
                    _write(OUT / "member_errors.json", {"errors": errors})
                    _write(OUT / "member_progress.json", {"processed": completed, "total": len(plan), "updated_at": datetime.now(CN_TZ).isoformat()})
                following = next(jobs, None)
                if following:
                    pending[executor.submit(one, following)] = following
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        _write(OUT / "member_errors.json", {"errors": errors})


def audit(days: list[str]) -> dict:
    from replay_sources import price_requirements
    optional_times = []
    gaps = {key: [] for key in ("pool", "ladder", "reasons", "market", "seal_action", "first_limit_attack_time", "prices", "opening_reference", "members", "breadth")}
    required_prices = {}
    for code, dates in price_requirements(days).items():
        for day in dates:
            required_prices.setdefault(day, set()).add(code)
    for day in days:
        folder = RAW / day
        for kind, name in [("pool", "zt_pool.json"), ("ladder", "limit_ladder.json"), ("reasons", "history_limit_resumption.json")]:
            path = folder / name
            try:
                body = _read(path)
                if kind == "pool":
                    if body.get("date") != day or body.get("count") != len(body["stocks"]):
                        raise ValueError("涨停池日期或数量错误")
                elif kind == "ladder":
                    _ladder_rows(body, day)
                else:
                    rows = reason_rows(body, day)
                    pool_path = folder / "zt_pool.json"
                    required = {r["code"] for r in _read(pool_path)["stocks"]}
                    available = {str(r[0]) for r in rows if str(r[17]).strip()}
                    if required - available:
                        gaps[kind].append({"date": day, "missing_codes": sorted(required - available)})
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
                gaps[kind].append({"date": day, "error": str(exc)})
        market_path = OUT / "market" / f"{day}.json"
        if not market_path.exists():
            gaps["market"].append(day)
            gaps["seal_action"].append(day)
        else:
            market = _read(market_path)
            missing = [x["code"] for x in market["stocks"] if x.get("has_seal_action") is None]
            if missing:
                gaps["seal_action"].append({"date": day, "missing_codes": missing})
            if market.get("missing_kpl_limit_codes"):
                gaps["market"].append({"date": day, "missing_codes": market["missing_kpl_limit_codes"]})
            missing_times = [x["code"] for x in market["stocks"] if x.get("closed_limit") and not x.get("first_limit_attack_ts")]
            optional = [x["code"] for x in market["stocks"] if x.get("failed_limit") and not x.get("first_limit_attack_ts")]
            if optional:
                optional_times.append({"date": day, "missing_codes": optional})
            if missing_times:
                gaps["first_limit_attack_time"].append({"date": day, "missing_codes": missing_times})
        price_path = OUT / "prices" / f"{day}.json"
        prices = {x["code"]: x for x in _read(price_path)["stocks"]} if price_path.exists() else {}
        applicable = {c for c in required_prices.get(day, set()) if prices.get(c, {}).get("reference_status") != "not_applicable_suspended"}
        missing_prices = sorted(c for c in applicable if prices.get(c, {}).get("open") is None or prices.get(c, {}).get("close") is None)
        missing_refs = sorted(c for c in applicable if prices.get(c, {}).get("open_pct") is None)
        if missing_prices:
            gaps["prices"].append({"date": day, "missing_codes": missing_prices})
        if missing_refs:
            gaps["opening_reference"].append({"date": day, "missing_codes": missing_refs})
    for day, plate in member_plan(days):
        if not (KPL / "plate_members" / day / f"{plate}.json").exists() and membership_store.snapshot(day, plate) is None:
            gaps["members"].append([day, plate])
        breadth_path = OUT / "breadth" / day / f"{plate}.json"
        if membership_store.snapshot(day, plate) is None and (not breadth_path.exists() or _read(breadth_path).get("limit_count") is None):
            gaps["breadth"].append([day, plate])
    result = {"start": days[0], "end": days[-1], "trade_days": len(days),
              "checked_at": datetime.now(CN_TZ).isoformat(), "gaps": gaps,
              "optional_missing": {"failed_limit_first_touch_time": optional_times},
              "complete": False,
              "required_fields_complete": not any(gaps.values()),
              "note": "炸板首次触板时间允许为空，列于optional_missing；历史成员为供应商补采返回版本。字段齐备不等同于历史当日快照。"}
    _write(OUT / "coverage.json", result)
    print("日期", days[0], days[-1], "缺口", {k: len(v) for k, v in gaps.items()}, flush=True)
    return result


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=["kpl", "import-members", "market", "attack-times", "prices", "price-gaps", "status", "references", "index-prices", "members", "audit", "all"])
    p.add_argument("--start")
    p.add_argument("--end")
    args = p.parse_args()
    now = datetime.now(CN_TZ)
    # 完整复盘只处理已收盘日期；是否已入库由响应日期验证。
    cutoff = now.date() if now.hour >= 16 else now.date() - timedelta(days=1)
    start = args.start or min(x.parent.name for x in RAW.glob("*/zt_pool.json"))
    end = args.end or cutoff.isoformat()
    days = trading_days(start, end)
    if not days:
        raise ValueError("范围内没有交易日")
    print("范围", days[0], days[-1], len(days), flush=True)
    if args.stage == "all":
        from replay_sources import run_market, run_prices, run_attack_times, run_price_gaps
        run_kpl(days)
        run_market(days)
        run_attack_times(days)
        run_prices(days)
        run_price_gaps(days)
        from replay_status import run_status
        run_status(days)
        from replay_reference import run_references
        run_references(days)
        run_members(days)
    elif args.stage == "import-members":
        import_members()
    elif args.stage == "kpl":
        run_kpl(days)
    elif args.stage in ("market", "prices"):
        from replay_sources import run_market, run_prices
        (run_market if args.stage == "market" else run_prices)(days)
    elif args.stage == "members":
        run_members(days)
    elif args.stage == "attack-times":
        from replay_sources import run_attack_times
        run_attack_times(days)
    elif args.stage == "index-prices":
        from replay_sources import run_prices
        run_prices(days, fetch=False)
    elif args.stage == "price-gaps":
        from replay_sources import run_price_gaps
        run_price_gaps(days)
    elif args.stage == "references":
        from replay_reference import run_references
        run_references(days)
    elif args.stage == "status":
        from replay_status import run_status
        run_status(days)
    audit(days)


if __name__ == "__main__":
    main()
