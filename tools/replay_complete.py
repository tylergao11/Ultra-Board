"""无人值守补缺：一次初扫、按缺项补采、有限重试、最后汇总。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta
import ctypes
import msvcrt
import re
import sys
import time

from bs4 import BeautifulSoup
import requests

from replay_backfill import RAW, OUT, CN_TZ, audit, trading_days, run_kpl, run_members
from replay_sources import DATA, fetch_year, run_prices, run_market, market_day, add_seal_actions, stamp
from replay_status import run_status
from replay_reference import run_references
from ultraboard.kaipanla.query import _read, _write


def wait_process(pid):
    """接续已存在的批次；由操作系统等待退出，不由模型轮询。"""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if kernel.WaitForSingleObject(handle, 0xFFFFFFFF) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)


def fill_dabanke_times(days):
    """每只股票只取一次打板客历史页，用其中日期和时间补首次进攻。"""
    missing = {}
    for day in days:
        for row in market_day(day)["stocks"]:
            if row.get("closed_limit") and not row.get("first_limit_ts"):
                missing.setdefault(row["code"], set()).add(day)
    cache_root = DATA / "dabanke" / "stock_attack_times"
    cache_root.mkdir(parents=True, exist_ok=True)

    def one(code):
        path = cache_root / f"{code}.json"
        through = max(missing[code])
        if path.exists():
            cached = _read(path)
            captured = cached.get("captured_at", "")
            if (cached.get("complete_through", "") >= through
                    or captured[:10] > through
                    or (captured[:10] == through and captured[11:16] >= "16:00")):
                return code, cached, None
        url = f"https://dabanke.com/gupiao-{code}.html"
        errors = []
        for attempt in range(3):
            try:
                response = requests.get(url, timeout=20)
                response.raise_for_status()
                response.encoding = "utf-8"
                soup = BeautifulSoup(response.text, "html.parser")
                if code not in response.text:
                    raise ValueError("个股页缺少股票编号")
                events = {}
                for row in soup.select("table tr"):
                    text = row.get_text(" ", strip=True)
                    match = re.match(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\b", text)
                    if match:
                        day, value = match.groups()
                        events[day] = min(value, events.get(day, value))
                body = {"code": code, "provider": "dabanke_stock_history", "source_url": url,
                        "captured_at": datetime.now(CN_TZ).isoformat(), "complete_through": through,
                        "attack_times": events}
                _write(path, body)
                return code, body, None
            except Exception as exc:
                errors.append(str(exc))
                time.sleep(attempt + 1)
        return code, None, errors[-1]

    found, errors = {}, []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for index, (code, body, error) in enumerate(pool.map(one, sorted(missing)), 1):
            if error:
                errors.append({"code": code, "error": error})
            else:
                found[code] = body
            if index % 250 == 0 or index == len(missing):
                print(f"打板客个股历史 {index}/{len(missing)} 请求失败{len(errors)}", flush=True)
    filled = 0
    for day in days:
        path = OUT / "market" / f"{day}.json"
        body, changed = market_day(day), False
        for row in body["stocks"]:
            value = (found.get(row["code"]) or {}).get("attack_times", {}).get(day)
            if row.get("has_limit_attack") and not row.get("first_limit_ts") and value:
                row["first_limit_ts"] = stamp(day, value)
                row["first_limit_time_source"] = {
                    "provider": "dabanke", "page": f"gupiao-{row['code']}.html", "field": "history_event_time"
                }
                changed = True
                filled += 1
        if changed:
            add_seal_actions(body)
            _write(path, body)
    _write(OUT / "dabanke_time_progress.json",
           {"requested_stocks": len(missing), "fetched_stocks": len(found), "filled_rows": filled, "errors": errors})
    print(f"打板客首次进攻时间补回 {filled} 条", flush=True)


def fill_times(days, attempts):
    """只补缺少的行情池；同花顺既有字段优先，绝不以末封代首封。"""
    from ultraboard.ths import open_limit_pool, limit_pool
    fill_dabanke_times(days)
    error_path = OUT / "time_gap_errors.json"
    prior_errors = _read(error_path).get("errors", []) if error_path.exists() else []
    exhausted = {(item.get("date"), item.get("pool")) for item in prior_errors}
    jobs = []
    for day in days:
        body = market_day(day)
        for closed, folder in ((True, "limit_pool"), (False, "open_limit_pool")):
            if not closed:
                continue  # 用户允许炸板首次触板时间留空，不再追补。
            if any(r.get("has_limit_attack") and not r.get("first_limit_ts")
                   and r.get("closed_limit") is closed for r in body["stocks"]):
                pool_name = "limit" if closed else "open_limit"
                if (day, pool_name) not in exhausted and not (DATA / "ths" / folder / f"{day}.json").exists():
                    jobs.append((day, closed))

    def one(job):
        day, closed = job
        errors = []
        for _ in range(attempts):
            try:
                if not closed:
                    payload = open_limit_pool.load_day(day, fetch_missing=True)
                    return day, payload["stocks"], None
                rows, total = limit_pool._fetch_raw_day(day)
                normalized = []
                for row in rows:
                    first = int(row["first_limit_up_time"])
                    if datetime.fromtimestamp(first, CN_TZ).date().isoformat() != day:
                        raise ValueError("首封时间不属于请求日期")
                    normalized.append({"code": str(row["code"]).zfill(6), "name": row["name"],
                                       "first_limit_ts": first,
                                       "final_limit_ts": int(row["last_limit_up_time"]),
                                       "open_count": int(row["open_num"]),
                                       "change_rate": float(row["change_rate"]),
                                       "closed_limit": True, "failed_limit": False})
                path = DATA / "ths" / "limit_time_gaps" / f"{day}.json"
                _write(path, {"date": day, "raw_rows": rows, "count": total, "stocks": normalized})
                return day, normalized, None
            except Exception as exc:
                errors.append(str(exc))
        return day, [], {"date": day, "pool": "limit" if closed else "open_limit", "errors": errors}

    errors = list(prior_errors)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for day, rows, error in pool.map(one, jobs):
            if error:
                errors.append(error)
                continue
            body = market_day(day)
            facts = {r["code"]: r for r in body["stocks"]}
            for row in rows:
                current = facts.setdefault(row["code"], {"code": row["code"]})
                current.update({k: v for k, v in row.items() if v is not None})
                current.update(provider="tonghuashun_limit_time_gap_fill")
                if "closed_limit" not in row:
                    current.update(closed_limit=False, failed_limit=True)
            body["stocks"] = list(facts.values())
            add_seal_actions(body)
            _write(OUT / "market" / f"{day}.json", body)
    _write(error_path, {"errors": errors})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--wait-pid", type=int)
    parser.add_argument("--attempts", type=int, choices=(1, 2, 3), default=2)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "complete.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0"); lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        with (OUT / "complete.log").open("a", encoding="utf-8", buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
            def state(stage, **extra):
                _write(OUT / "complete_state.json", {"stage": stage,
                       "updated_at": datetime.now(CN_TZ).isoformat(), **extra})
            try:
                if args.wait_pid:
                    state("waiting_existing_batch", pid=args.wait_pid)
                    wait_process(args.wait_pid)
                now = datetime.now(CN_TZ)
                end = args.end or (now.date() if now.hour >= 16 else now.date() - timedelta(days=1)).isoformat()
                start = args.start or min(p.parent.name for p in RAW.glob("*/zt_pool.json"))
                days = trading_days(start, end)
                state("scan")
                gaps = audit(days)["gaps"]
                errors = []
                def run(name, function):
                    state(name)
                    for attempt in range(args.attempts):
                        try:
                            function(); return
                        except Exception as exc:
                            print(name, attempt + 1, repr(exc), flush=True)
                    errors.append(name)
                if any(gaps[k] for k in ("pool", "ladder", "reasons")):
                    run("kaipanla", lambda: run_kpl(days))
                if gaps["market"] or gaps["seal_action"]:
                    run("market", lambda: run_market(days))
                if gaps["first_limit_attack_time"]:
                    run("first_limit_times", lambda: fill_times(days, args.attempts))
                if gaps["prices"]:
                    def prices():
                        tasks = {(code, int(item["date"][:4]), item["date"])
                                 for item in gaps["prices"] for code in item["missing_codes"]}
                        for _ in range(args.attempts):
                            failed = []
                            with ThreadPoolExecutor(max_workers=4) as pool:
                                for task, result in zip(tasks, pool.map(fetch_year, tasks)):
                                    if result[1]:
                                        print(result, flush=True)
                                        failed.append(task)
                            tasks = failed
                            if not tasks: break
                        run_prices(days, fetch=False)
                    run("prices", prices)
                    run("suspensions", lambda: run_status(days))
                if gaps["opening_reference"] or gaps["prices"]:
                    run("references", lambda: run_references(days))
                if gaps["members"] or gaps["breadth"] or gaps["pool"] or gaps["reasons"]:
                    run("members", lambda: run_members(days, attempts=args.attempts))
                state("final_scan")
                final = audit(days)
                counts = {key: len(value) for key, value in final["gaps"].items()}
                # 零缺项也仅代表字段齐备，不冒充全部来源口径已验收。
                state("needs_attention" if errors or any(counts.values()) else "ready_for_review",
                      gaps=counts, failed_stages=errors, report="data/replay/coverage.json")
                return 2 if errors or any(counts.values()) else 0
            except Exception as exc:
                state("failed", error=repr(exc))
                raise


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
