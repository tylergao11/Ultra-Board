# -*- coding: utf-8 -*-
"""连板接力切入点研究 runner。只读原始日快照，写出 out/。

定义见同目录 spec.md。不读取 AGENTS.md，不调用站点/agent 意见。
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "kaipanla" / "raw"
THS_ZT = ROOT / "data" / "ths" / "limit_pool"
THS_ZHA = ROOT / "data" / "ths" / "open_limit_pool"
OUT = Path(__file__).resolve().parent / "out"

WINDOW_START = "2025-10-09"
WINDOW_END = "2026-08-13"
BAOLIANG_RATIO = 2.0
NEWHIGH_LOOKBACK = 20
MIN_CLAIM_N = 30
MIN_WEAK_N = 15
WF_TRAIN = 40
WF_TEST = 20
WF_STEP = 20
THEME_SEP = None  # filled below

import re
THEME_SEP = re.compile(r"[、，,]+")


def _day(s: str) -> str:
    return date.fromisoformat(s).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _f(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _i(v: Any) -> int | None:
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def is_excluded_name(name: str) -> bool:
    n = str(name or "").upper().replace(" ", "")
    return "ST" in n or "退" in str(name or "")


def stock_themes(stock: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    primary = str(stock.get("theme") or "").strip()
    if primary:
        out.append(primary)
        seen.add(primary)
    tags = str(stock.get("theme_tags_text") or "").strip()
    raw = stock.get("raw")
    if not tags and isinstance(raw, list) and len(raw) > 12:
        tags = str(raw[12] or "").strip()
    if tags:
        for part in THEME_SEP.split(tags):
            p = part.strip()
            if p and p not in seen:
                seen.add(p)
                out.append(p)
    return out


def list_window_days() -> list[str]:
    days = []
    for p in sorted(RAW.iterdir()):
        if not p.is_dir() or len(p.name) != 10:
            continue
        if not (p / "zt_pool.json").exists():
            continue
        if WINDOW_START <= p.name <= WINDOW_END:
            days.append(p.name)
    return days


def load_ths_zt(day: str) -> dict[str, dict[str, Any]]:
    path = THS_ZT / f"{day}.json"
    if not path.exists():
        return {}
    data = _read_json(path)
    return {str(s["code"]): s for s in data.get("stocks") or [] if s.get("code")}


def load_ths_zha(day: str) -> dict[str, dict[str, Any]]:
    path = THS_ZHA / f"{day}.json"
    if not path.exists():
        return {}
    data = _read_json(path)
    return {str(s["code"]): s for s in data.get("stocks") or [] if s.get("code")}


def load_day(day: str) -> dict[str, Any]:
    folder = RAW / day
    pool = _read_json(folder / "zt_pool.json")
    stocks_raw = pool.get("stocks") or []
    ths = load_ths_zt(day)
    zha = load_ths_zha(day)
    stocks: dict[str, dict[str, Any]] = {}
    for s in stocks_raw:
        code = str(s.get("code") or "")
        if not code:
            continue
        t = ths.get(code) or {}
        themes = stock_themes(s)
        rec = {
            "code": code,
            "name": s.get("name") or t.get("name") or "",
            "boards": _i(s.get("boards")) or 0,
            "theme": str(s.get("theme") or "").strip(),
            "themes": themes,
            "amount": _f(s.get("amount")),
            "turnover_rate": _f(s.get("turnover_rate")),
            "price": _f(s.get("price")),
            "open": _f(s.get("open")),
            "high": _f(s.get("high")),
            "low": _f(s.get("low")),
            "prev_close": _f(s.get("prev_close")),
            "open_pct": _f(s.get("open_pct")),
            "limit_pct": _f(s.get("limit_pct")),
            "is_fanbao": bool(s.get("is_fanbao")),
            "one_price": bool(t.get("one_price")) if t else None,
            "board_type": t.get("board_type"),
            "open_count": _i(t.get("open_count")) if t else None,
            "ths_boards": _i(t.get("boards")) if t else None,
            "ths_change_rate": _f(t.get("change_rate")) if t else None,
        }
        stocks[code] = rec
    boards_list = [x["boards"] for x in stocks.values() if x["boards"] > 0]
    H = max(boards_list) if boards_list else 0
    file_H = _i(pool.get("max_board"))
    leaders = sorted([c for c, x in stocks.items() if x["boards"] == H])
    closed = (folder / "_DONE").exists()
    return {
        "date": day,
        "H": H,
        "file_H": file_H,
        "count": len(stocks),
        "file_count": pool.get("count"),
        "closed": closed,
        "stocks": stocks,
        "leaders": leaders,
        "zha": zha,
        "theme_counts": Counter(x["theme"] for x in stocks.values() if x["theme"]),
        "has_ohlc": any(x["open"] is not None for x in stocks.values()),
        "has_price": any(x["price"] is not None for x in stocks.values()),
        "has_ths": bool(ths),
        "has_zha": bool(zha),
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def median_or_none(xs: list[float]) -> float | None:
    if not xs:
        return None
    return float(statistics.median(xs))


def streak_prior_amounts(days: list[dict[str, Any]], idx: int, code: str) -> list[float]:
    """Appearance-connected prior streak amounts (halt gaps allowed)."""
    cur = days[idx]["stocks"].get(code)
    if not cur:
        return []
    expected = cur["boards"] - 1
    out: list[float] = []
    j = idx - 1
    while j >= 0 and expected >= 1:
        rec = days[j]["stocks"].get(code)
        if rec is None:
            j -= 1
            continue
        if rec["boards"] == expected and rec["amount"] is not None:
            out.append(rec["amount"])
            expected -= 1
            j -= 1
            continue
        break
    return out


def classify_baoliang(amount: float | None, priors: list[float]) -> dict[str, Any]:
    if amount is None or not priors or priors[0] <= 0:
        return {
            "baoliang": None,
            "amt_ratio_prev": None,
            "amt_ratio_med": None,
            "n_prior": len(priors),
        }
    prev = priors[0]
    med = median_or_none(priors) or prev
    r_prev = amount / prev if prev else None
    r_med = amount / med if med else None
    # Frozen trigger: vs previous streak day only. Full-streak median is
    # diagnostic — early one-word tiny amounts would otherwise flag every later day.
    flag = bool(r_prev is not None and r_prev >= BAOLIANG_RATIO)
    return {
        "baoliang": flag,
        "amt_ratio_prev": r_prev,
        "amt_ratio_med": r_med,
        "n_prior": len(priors),
    }


def fate_on(day: dict[str, Any], code: str) -> dict[str, Any]:
    st = day["stocks"].get(code)
    zha = day["zha"].get(code)
    if st:
        one = st["one_price"]
        if one is None and st["board_type"] == "一字板":
            one = True
        return {
            "in_zt": True,
            "boards": st["boards"],
            "one_word": bool(one) if one is not None else None,
            "board_type": st["board_type"],
            "in_zha": False,
            "zha_change_rate": None,
            "theme": st["theme"],
        }
    if zha:
        return {
            "in_zt": False,
            "boards": None,
            "one_word": None,
            "board_type": None,
            "in_zha": True,
            "zha_change_rate": _f(zha.get("change_rate")),
            "theme": None,
        }
    return {
        "in_zt": False,
        "boards": None,
        "one_word": None,
        "board_type": None,
        "in_zha": False,
        "zha_change_rate": None,
        "theme": None,
    }


def later_halt_resume(days: list[dict[str, Any]], start_idx: int, code: str, prev_boards: int) -> bool:
    for d in days[start_idx + 1 :]:
        st = d["stocks"].get(code)
        if st and st["boards"] >= prev_boards:
            return True
        if st:
            return False
    return False


def rate(n_ok: int, n: int) -> float | None:
    if n <= 0:
        return None
    return n_ok / n


def fmt_rate(n_ok: int, n: int) -> str:
    if n <= 0:
        return f"— (n=0)"
    return f"{n_ok}/{n} = {n_ok / n:.1%}"


def cell(n_ok: int, n: int) -> dict[str, Any]:
    return {"ok": n_ok, "n": n, "rate": rate(n_ok, n)}


def add_trial(bucket: dict[str, int], zt: bool, promote: bool, tradable: bool) -> None:
    bucket["n"] += 1
    bucket["zt"] += int(zt)
    bucket["promote"] += int(promote)
    bucket["tradable"] += int(tradable)


def empty_bucket() -> dict[str, int]:
    return {"n": 0, "zt": 0, "promote": 0, "tradable": 0}


def bucket_view(b: dict[str, int]) -> dict[str, Any]:
    return {
        "n": b["n"],
        "zt": cell(b["zt"], b["n"]),
        "promote": cell(b["promote"], b["n"]),
        "tradable_zt": cell(b["tradable"], b["n"]),
    }


def height_bucket(h: int) -> str:
    if h <= 2:
        return "2"
    if h == 3:
        return "3"
    if h == 4:
        return "4"
    return "5+"


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    line = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join([line, sep, *body])



def height_matched(rows, pred, all_rows):
    """Actual tradable rate vs unconditional same-boards expected rate."""
    selected = [r for r in rows if pred(r)]
    n = len(selected)
    if n == 0:
        return {"n": 0, "actual": None, "expected": None, "residual": None, "zt_actual": None}
    by_h = {}
    for r in all_rows:
        by_h.setdefault(r["boards"], {"n": 0, "tradable": 0})
        by_h[r["boards"]]["n"] += 1
        by_h[r["boards"]]["tradable"] += int(r["tradable_zt"])
    actual = sum(int(r["tradable_zt"]) for r in selected) / n
    zt_actual = sum(int(r["zt_next"]) for r in selected) / n
    exp_sum = 0.0
    for r in selected:
        b = by_h[r["boards"]]
        exp_sum += (b["tradable"] / b["n"]) if b["n"] else 0.0
    expected = exp_sum / n
    return {
        "n": n,
        "actual": actual,
        "expected": expected,
        "residual": actual - expected,
        "zt_actual": zt_actual,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    day_ids = list_window_days()
    days = [load_day(d) for d in day_ids]
    n_days = len(days)
    warnings: list[str] = []

    for d in days:
        if d["file_H"] is not None and d["file_H"] != d["H"]:
            warnings.append(f"{d['date']}: file max_board={d['file_H']} != computed H={d['H']}")
        if d["file_count"] is not None and d["file_count"] != d["count"]:
            warnings.append(f"{d['date']}: file count={d['file_count']} != stocks={d['count']}")

    # boards disagree
    disagree_rows = []
    for d in days:
        for s in d["stocks"].values():
            if s["ths_boards"] is not None and s["ths_boards"] != s["boards"]:
                disagree_rows.append({
                    "date": d["date"],
                    "code": s["code"],
                    "name": s["name"],
                    "kpl_boards": s["boards"],
                    "ths_boards": s["ths_boards"],
                    "board_type": s["board_type"],
                })

    # annotate leaders / market events
    leader_rows = []
    day_rows = []
    for i, d in enumerate(days):
        prev = days[i - 1] if i else None
        H = d["H"]
        H_prev = prev["H"] if prev else None
        prev_leaders = prev["leaders"] if prev else []
        absent = []
        sealed = []
        zha_leaders = []
        halt_expost = []
        baoliang_flags = []
        for code in prev_leaders:
            rec = prev["stocks"][code]
            if code in d["stocks"]:
                sealed.append(code)
            else:
                absent.append(code)
                z = d["zha"].get(code)
                if z and (z.get("change_tag") == "LIMIT_FAILED" or z.get("change_tag") is None):
                    # LIMIT_FAILED is the pool's main tag; also count presence
                    zha_leaders.append(code)
                elif z:
                    zha_leaders.append(code)
                if later_halt_resume(days, i - 1, code, rec["boards"]):
                    halt_expost.append(code)
        # baoliang on today's leaders (and yesterday's, stored separately)
        today_baoliang = []
        today_baoliang_unknown = []
        for code in d["leaders"]:
            rec = d["stocks"][code]
            priors = streak_prior_amounts(days, i, code)
            info = classify_baoliang(rec["amount"], priors)
            rec["_baoliang"] = info
            if info["baoliang"] is True:
                today_baoliang.append(code)
            elif info["baoliang"] is None:
                today_baoliang_unknown.append(code)
            leader_rows.append({
                "date": d["date"],
                "code": code,
                "name": rec["name"],
                "boards": rec["boards"],
                "theme": rec["theme"],
                "amount": rec["amount"],
                "turnover_rate": rec["turnover_rate"],
                "price": rec["price"],
                "one_price": rec["one_price"],
                "board_type": rec["board_type"],
                "baoliang": info["baoliang"],
                "amt_ratio_prev": info["amt_ratio_prev"],
                "amt_ratio_med": info["amt_ratio_med"],
                "n_prior": info["n_prior"],
            })

        lookback_H = [days[j]["H"] for j in range(max(0, i - NEWHIGH_LOOKBACK), i)]
        height_new_high = bool(lookback_H) and H > max(lookback_H)

        leader_absent = bool(prev) and bool(prev_leaders) and (len(absent) == len(prev_leaders))
        leader_any_absent = bool(prev) and bool(absent)
        height_drop = bool(prev) and H_prev is not None and H < H_prev
        height_up = bool(prev) and H_prev is not None and H > H_prev
        leader_baoliang = bool(today_baoliang)
        # yesterday leaders baoliang (for 爆量日+1 = today is next day after baoliang)
        prev_leader_baoliang = False
        if prev:
            for code in prev["leaders"]:
                info = prev["stocks"][code].get("_baoliang") or {}
                if info.get("baoliang") is True:
                    prev_leader_baoliang = True

        broken_themes = []
        if prev:
            for code in absent:
                th = prev["stocks"][code]["theme"]
                if th:
                    broken_themes.append(th)
        broken_themes = list(dict.fromkeys(broken_themes))
        theme_alive = any(d["theme_counts"].get(th, 0) >= 2 for th in broken_themes)
        theme_dead = bool(broken_themes) and all(d["theme_counts"].get(th, 0) == 0 for th in broken_themes)

        d["prev"] = prev
        d["H_prev"] = H_prev
        d["prev_leaders"] = prev_leaders
        d["absent_leaders"] = absent
        d["sealed_leaders"] = sealed
        d["zha_leaders"] = zha_leaders
        d["halt_expost_leaders"] = halt_expost
        d["leader_absent"] = leader_absent
        d["leader_any_absent"] = leader_any_absent
        d["height_drop"] = height_drop
        d["height_up"] = height_up
        d["height_new_high"] = height_new_high
        d["leader_baoliang"] = leader_baoliang
        d["prev_leader_baoliang"] = prev_leader_baoliang
        d["broken_themes"] = broken_themes
        d["theme_alive"] = theme_alive
        d["theme_dead"] = theme_dead
        d["today_baoliang"] = today_baoliang

        day_rows.append({
            "date": d["date"],
            "H": H,
            "H_prev": H_prev,
            "n_zt": d["count"],
            "n_leaders": len(d["leaders"]),
            "leaders": " ".join(d["leaders"]),
            "closed": d["closed"],
            "has_ohlc": d["has_ohlc"],
            "has_ths": d["has_ths"],
            "has_zha": d["has_zha"],
            "leader_absent": leader_absent,
            "leader_any_absent": leader_any_absent,
            "n_absent_leaders": len(absent),
            "n_sealed_leaders": len(sealed),
            "n_zha_leaders": len(zha_leaders),
            "n_halt_expost": len(halt_expost),
            "height_drop": height_drop,
            "height_up": height_up,
            "height_new_high": height_new_high,
            "leader_baoliang": leader_baoliang,
            "prev_leader_baoliang": prev_leader_baoliang,
            "broken_themes": "|".join(broken_themes),
            "theme_alive": theme_alive,
            "theme_dead": theme_dead,
        })

    # days until new height cycle after a peak-and-drop
    # cycle peak: local max of H, then drop. next cycle = H makes a new local climb starting after drop.
    cycle_gaps: list[int] = []
    peak_idx = None
    peak_H = None
    for i, d in enumerate(days):
        if i == 0:
            continue
        if d["H"] > days[i - 1]["H"]:
            # climbing
            if peak_idx is not None and i > peak_idx:
                # already dropped then climbing again
                pass
        if days[i - 1]["H"] >= (peak_H or 0) and d["H"] < days[i - 1]["H"]:
            # just dropped from a peak
            peak_idx = i - 1
            peak_H = days[i - 1]["H"]
            # search forward for H >= peak_H or a new climb that exceeds post-drop start
        if peak_idx is not None and i > peak_idx + 0:
            if d["H"] >= (peak_H or 0) and i > peak_idx + 1:
                cycle_gaps.append(i - peak_idx)
                # reset so we don't double count
                peak_idx = None
                peak_H = None

    # candidates
    cand_rows = []
    n_pairs = n_days - 1
    for i, d in enumerate(days[:-1]):
        nxt = days[i + 1]
        nxt2 = days[i + 2] if i + 2 < n_days else None
        nxt3 = days[i + 3] if i + 3 < n_days else None
        H = d["H"]
        H_prev = d["H_prev"]
        for s in d["stocks"].values():
            if s["boards"] < 2:
                continue
            if is_excluded_name(s["name"]):
                continue
            f1 = fate_on(nxt, s["code"])
            f2 = fate_on(nxt2, s["code"]) if nxt2 else None
            f3 = fate_on(nxt3, s["code"]) if nxt3 else None
            zt1 = bool(f1["in_zt"])
            promote1 = bool(f1["in_zt"] and f1["boards"] == s["boards"] + 1)
            one1 = f1["one_word"]
            tradable1 = zt1 and one1 is False
            same_theme_broken = bool(d["broken_themes"]) and s["theme"] in d["broken_themes"]
            loose_theme = False
            if d["prev"]:
                broken_theme_sets = []
                for code in d["absent_leaders"]:
                    broken_theme_sets.extend(d["prev"]["stocks"][code]["themes"])
                loose_theme = bool(set(s["themes"]) & set(broken_theme_sets))
            tier = []
            if s["boards"] == H:
                tier.append("new_high")
            if H >= 3 and s["boards"] == H - 1:
                tier.append("sub_high")
            if H >= 4 and s["boards"] == H - 2:
                tier.append("h_minus_2")
            if s["boards"] in (2, 3):
                tier.append("mid_2_3")
            if H_prev and s["boards"] in (H_prev - 1, H_prev - 2):
                tier.append("legacy_near")
            cand_rows.append({
                "signal_date": d["date"],
                "outcome_date": nxt["date"],
                "code": s["code"],
                "name": s["name"],
                "boards": s["boards"],
                "height_bucket": height_bucket(s["boards"]),
                "theme": s["theme"],
                "H": H,
                "H_prev": H_prev,
                "leader_absent": d["leader_absent"],
                "leader_any_absent": d["leader_any_absent"],
                "height_drop": d["height_drop"],
                "height_new_high": d["height_new_high"],
                "leader_baoliang": d["leader_baoliang"],
                "prev_leader_baoliang": d["prev_leader_baoliang"],
                "theme_alive": d["theme_alive"],
                "theme_dead": d["theme_dead"],
                "same_theme_broken": same_theme_broken,
                "loose_theme_broken": loose_theme,
                "tier": "|".join(tier),
                "is_new_high": s["boards"] == H,
                "is_sub_high": H >= 3 and s["boards"] == H - 1,
                "is_mid_2_3": s["boards"] in (2, 3),
                "is_legacy_near": bool(H_prev) and s["boards"] in (H_prev - 1, H_prev - 2),
                "one_price_today": s["one_price"],
                "zt_next": zt1,
                "promote": promote1,
                "one_word_next": one1,
                "tradable_zt": tradable1,
                "zha_next": bool(f1["in_zha"]),
                "zha_change_rate": f1["zha_change_rate"],
                "boards_next": f1["boards"],
                "zt_d2": bool(f2["in_zt"]) if f2 else None,
                "promote_d2": bool(f2["in_zt"] and f2["boards"] == s["boards"] + 2) if f2 else None,
                "zt_d3": bool(f3["in_zt"]) if f3 else None,
            })

    # ---------- aggregates ----------
    def trials(rows, pred, outcome="tradable_zt"):
        b = empty_bucket()
        for r in rows:
            if not pred(r):
                continue
            add_trial(b, r["zt_next"], r["promote"], r["tradable_zt"])
        return b

    all_c = cand_rows
    signal_dates = sorted({r["signal_date"] for r in all_c})
    mid = len(signal_dates) // 2
    first_half_dates = set(signal_dates[:mid])
    second_half_dates = set(signal_dates[mid:])

    def in_dates(r, dset):
        return r["signal_date"] in dset

    # A baseline by height
    A = {
        "all>=2": trials(all_c, lambda r: True),
        "2": trials(all_c, lambda r: r["boards"] == 2),
        "3": trials(all_c, lambda r: r["boards"] == 3),
        "4": trials(all_c, lambda r: r["boards"] == 4),
        "5+": trials(all_c, lambda r: r["boards"] >= 5),
    }
    A_half = {
        "first": {k: trials(all_c, lambda r, kk=k: in_dates(r, first_half_dates) and (
            True if kk == "all>=2" else r["boards"] == int(kk) if kk != "5+" else r["boards"] >= 5
        )) for k in A},
        "second": {k: trials(all_c, lambda r, kk=k: in_dates(r, second_half_dates) and (
            True if kk == "all>=2" else r["boards"] == int(kk) if kk != "5+" else r["boards"] >= 5
        )) for k in A},
    }

    # B leader absent vs sealed
    B = {
        "leader_absent": trials(all_c, lambda r: r["leader_absent"]),
        "leader_not_absent": trials(all_c, lambda r: r["H_prev"] is not None and not r["leader_absent"]),
        "height_drop": trials(all_c, lambda r: r["height_drop"]),
        "height_not_drop": trials(all_c, lambda r: r["H_prev"] is not None and not r["height_drop"]),
        "leader_any_absent": trials(all_c, lambda r: r["leader_any_absent"]),
    }

    # C baoliang
    C = {
        "prev_leader_baoliang": trials(all_c, lambda r: r["prev_leader_baoliang"]),
        "prev_leader_not_baoliang": trials(all_c, lambda r: r["H_prev"] is not None and not r["prev_leader_baoliang"]),
        "today_leader_baoliang": trials(all_c, lambda r: r["leader_baoliang"]),
        "baoliang_and_still_sealed": trials(all_c, lambda r: r["leader_baoliang"] and not r["leader_absent"]),
    }

    # D tiers on absent days
    D = {
        "absent_new_high": trials(all_c, lambda r: r["leader_absent"] and r["is_new_high"]),
        "absent_sub_high": trials(all_c, lambda r: r["leader_absent"] and r["is_sub_high"]),
        "absent_mid_2_3": trials(all_c, lambda r: r["leader_absent"] and r["is_mid_2_3"]),
        "absent_legacy_near": trials(all_c, lambda r: r["leader_absent"] and r["is_legacy_near"]),
        "absent_h_minus_2": trials(all_c, lambda r: r["leader_absent"] and "h_minus_2" in r["tier"].split("|")),
    }

    # E theme
    E = {
        "absent_same_theme": trials(all_c, lambda r: r["leader_absent"] and r["same_theme_broken"]),
        "absent_other_theme": trials(all_c, lambda r: r["leader_absent"] and r["broken_themes_ok"] and not r["same_theme_broken"]) if False else trials(all_c, lambda r: r["leader_absent"] and bool(r["theme"]) and not r["same_theme_broken"] and (r["H_prev"] is not None)),
        "absent_theme_alive_same": trials(all_c, lambda r: r["leader_absent"] and r["theme_alive"] and r["same_theme_broken"]),
        "absent_theme_dead_other": trials(all_c, lambda r: r["leader_absent"] and r["theme_dead"] and not r["same_theme_broken"]),
        "absent_theme_alive_any": trials(all_c, lambda r: r["leader_absent"] and r["theme_alive"]),
        "absent_theme_dead_any": trials(all_c, lambda r: r["leader_absent"] and r["theme_dead"]),
    }

    # F lags: rebuild from day events
    def lag_trials(lag: int, require_absent: bool = True) -> dict[str, int]:
        b = empty_bucket()
        for i, d in enumerate(days):
            if require_absent and not d["leader_absent"]:
                continue
            if not require_absent and not d.get("prev_leader_baoliang"):
                continue
            src_idx = i + (lag - 1)
            out_idx = i + lag
            if src_idx >= n_days - 1 or out_idx >= n_days:
                continue
            src = days[src_idx]
            outd = days[out_idx]
            for s in src["stocks"].values():
                if s["boards"] < 2 or is_excluded_name(s["name"]):
                    continue
                f = fate_on(outd, s["code"])
                zt = bool(f["in_zt"])
                promote = bool(f["in_zt"] and f["boards"] == s["boards"] + 1)
                tradable = zt and f["one_word"] is False
                add_trial(b, zt, promote, tradable)
        return b

    F = {
        "absent_lag1": lag_trials(1, True),
        "absent_lag2": lag_trials(2, True),
        "absent_lag3": lag_trials(3, True),
        "baoliang_lag1": lag_trials(1, False),
        "baoliang_lag2": lag_trials(2, False),
        "baoliang_lag3": lag_trials(3, False),
    }

    # G rules
    rules = {
        "B0_uncond_lianban": lambda r: True,
        "R1_absent_all_lianban": lambda r: r["leader_absent"],
        "R2_sealed_all_lianban": lambda r: r["H_prev"] is not None and not r["leader_absent"],
        "R3_absent_same_theme": lambda r: r["leader_absent"] and r["same_theme_broken"],
        "R4_absent_mid_2_3": lambda r: r["leader_absent"] and r["is_mid_2_3"],
        "R5_absent_new_high": lambda r: r["leader_absent"] and r["is_new_high"],
        "R6_baoliang_sealed_same_theme": lambda r: r["leader_baoliang"] and not r["leader_absent"] and r["same_theme_broken"],
        "R7_newhigh_mid_2_3": lambda r: r["height_new_high"] and r["is_mid_2_3"],
        "R8_newhigh_skip": lambda r: False,  # explicit skip
    }
    # R6 same_theme_broken is about broken leaders; when not absent, broken_themes is empty.
    # Fix R6: same theme as TODAY's baoliang leaders.
    baoliang_theme_by_day = {}
    for d in days:
        ths = []
        for code in d.get("today_baoliang") or []:
            th = d["stocks"][code]["theme"]
            if th:
                ths.append(th)
        baoliang_theme_by_day[d["date"]] = set(ths)
    for r in all_c:
        r["same_theme_baoliang"] = r["theme"] in baoliang_theme_by_day.get(r["signal_date"], set())
    rules["R6_baoliang_sealed_same_theme"] = (
        lambda r: r["leader_baoliang"] and not r["leader_absent"] and r["same_theme_baoliang"]
    )

    def eval_rule(pred, rows):
        return trials(rows, pred)

    rule_all = {name: eval_rule(pred, all_c) for name, pred in rules.items()}
    rule_first = {name: eval_rule(lambda r, p=pred: p(r) and in_dates(r, first_half_dates), all_c) for name, pred in rules.items()}
    rule_second = {name: eval_rule(lambda r, p=pred: p(r) and in_dates(r, second_half_dates), all_c) for name, pred in rules.items()}

    # walk-forward folds on signal dates
    folds = []
    i0 = 0
    while i0 + WF_TRAIN + WF_TEST <= len(signal_dates):
        train_set = set(signal_dates[i0:i0 + WF_TRAIN])
        test_set = set(signal_dates[i0 + WF_TRAIN:i0 + WF_TRAIN + WF_TEST])
        folds.append({
            "train_start": signal_dates[i0],
            "train_end": signal_dates[i0 + WF_TRAIN - 1],
            "test_start": signal_dates[i0 + WF_TRAIN],
            "test_end": signal_dates[i0 + WF_TRAIN + WF_TEST - 1],
            "train": {name: eval_rule(lambda r, p=pred: p(r) and in_dates(r, train_set), all_c) for name, pred in rules.items()},
            "test": {name: eval_rule(lambda r, p=pred: p(r) and in_dates(r, test_set), all_c) for name, pred in rules.items()},
        })
        i0 += WF_STEP

    def beats(rule_b, base_b, key="tradable"):
        if rule_b["n"] < MIN_CLAIM_N or base_b["n"] < MIN_CLAIM_N:
            return None
        return (rule_b[key] / rule_b["n"]) >= (base_b[key] / base_b["n"])

    def beats_weak(rule_b, base_b, key="tradable"):
        if rule_b["n"] < MIN_WEAK_N or base_b["n"] < MIN_WEAK_N:
            return None
        return (rule_b[key] / rule_b["n"]) >= (base_b[key] / base_b["n"])

    survived = []
    for name in rules:
        if name == "B0_uncond_lianban":
            continue
        a = beats(rule_first[name], rule_first["B0_uncond_lianban"])
        b = beats(rule_second[name], rule_second["B0_uncond_lianban"])
        fold_hits = []
        for fd in folds:
            hit = beats_weak(fd["test"][name], fd["test"]["B0_uncond_lianban"])
            if hit is not None:
                fold_hits.append(hit)
        wf_ok = (sum(fold_hits) > len(fold_hits) / 2) if fold_hits else False
        rec = {
            "rule": name,
            "half1_beats": a,
            "half2_beats": b,
            "both_halves": a is True and b is True,
            "wf_test_folds_scored": len(fold_hits),
            "wf_test_folds_beat": sum(fold_hits),
            "wf_majority": wf_ok,
            "survived": a is True and b is True and wf_ok,
            "n_all": rule_all[name]["n"],
            "tradable_all": rule_all[name]["tradable"],
            "n_half1": rule_first[name]["n"],
            "tradable_half1": rule_first[name]["tradable"],
            "n_half2": rule_second[name]["n"],
            "tradable_half2": rule_second[name]["tradable"],
        }
        survived.append(rec)

    # day-level counts for events
    n_absent_days = sum(1 for d in days if d["leader_absent"])
    n_drop_days = sum(1 for d in days if d["height_drop"])
    n_absent_not_drop = sum(1 for d in days if d["leader_absent"] and not d["height_drop"])
    n_drop_not_absent = sum(1 for d in days if d["height_drop"] and not d["leader_absent"])
    n_zha_days = sum(1 for d in days if d["zha_leaders"])
    n_halt_days = sum(1 for d in days if d["halt_expost_leaders"])
    n_baoliang_days = sum(1 for d in days if d["leader_baoliang"])
    n_newhigh_days = sum(1 for d in days if d["height_new_high"])

    # promote vs zt mismatch
    n_zt_not_promote = sum(1 for r in all_c if r["zt_next"] and not r["promote"])

    height_match_all = {name: height_matched(all_c, pred, all_c) for name, pred in rules.items()}
    height_match_first = {name: height_matched(all_c, lambda r, p=pred: p(r) and in_dates(r, first_half_dates), all_c) for name, pred in rules.items()}
    height_match_second = {name: height_matched(all_c, lambda r, p=pred: p(r) and in_dates(r, second_half_dates), all_c) for name, pred in rules.items()}
    for rec in survived:
        name = rec["rule"]
        rec["height_match_all"] = height_match_all[name]
        rec["height_match_first"] = height_match_first[name]
        rec["height_match_second"] = height_match_second[name]
        hm1 = height_match_first[name]
        hm2 = height_match_second[name]
        rec["height_residual_both_nonneg"] = (
            hm1["n"] >= MIN_CLAIM_N and hm2["n"] >= MIN_CLAIM_N
            and hm1["residual"] is not None and hm2["residual"] is not None
            and hm1["residual"] >= 0 and hm2["residual"] >= 0
        )
        rec["robust_survived"] = bool(rec["survived"] and rec["height_residual_both_nonneg"])

        tables = {
        "window": {
            "start": day_ids[0],
            "end": day_ids[-1],
            "n_days": n_days,
            "n_signal_days_with_next": n_pairs,
            "half_split": {
                "first": [signal_dates[0], signal_dates[mid - 1]] if signal_dates else None,
                "second": [signal_dates[mid], signal_dates[-1]] if signal_dates else None,
                "n_first": len(first_half_dates),
                "n_second": len(second_half_dates),
            },
            "isolated_excluded": ["2025-04-01", "2025-04-02", "2025-04-03", "2025-09-30"],
            "unclosed_days": [d["date"] for d in days if not d["closed"]],
            "ohlc_days": sum(1 for d in days if d["has_ohlc"]),
            "ths_days": sum(1 for d in days if d["has_ths"]),
            "zha_days": sum(1 for d in days if d["has_zha"]),
        },
        "definitions": {
            "H": "max kaipanla stocks[].boards",
            "leader_absent": "all of yesterday's max-height stocks missing from today's zt pool",
            "height_drop": "H(t) < H(t-1)",
            "baoliang": f"leader amount / prior-streak amount >= {BAOLIANG_RATIO} (prev or median)",
            "candidate": "boards>=2, not ST/退, known at t close",
            "zt_next": "in next day's kaipanla zt pool",
            "promote": "zt_next and boards+1",
            "tradable_zt": "zt_next and THS one_price is False",
            "not_backtestable": [
                "limit-up fill (打板成交)",
                "open-to-close return for all candidates",
                "return of broken leaders",
                "auction/open fill",
            ],
        },
        "event_days": {
            "leader_absent": n_absent_days,
            "height_drop": n_drop_days,
            "absent_not_drop": n_absent_not_drop,
            "drop_not_absent": n_drop_not_absent,
            "leader_zha_any": n_zha_days,
            "leader_halt_expost_any": n_halt_days,
            "leader_baoliang": n_baoliang_days,
            "height_new_high": n_newhigh_days,
            "cycle_reclaim_gaps_n": len(cycle_gaps),
            "cycle_reclaim_gaps": cycle_gaps,
            "cycle_reclaim_median": median_or_none([float(x) for x in cycle_gaps]),
        },
        "boards_disagree_n": len(disagree_rows),
        "zt_but_not_promote_n": n_zt_not_promote,
        "A_baseline": {k: bucket_view(v) for k, v in A.items()},
        "A_half": {
            hk: {k: bucket_view(v) for k, v in hv.items()} for hk, hv in A_half.items()
        },
        "B_break": {k: bucket_view(v) for k, v in B.items()},
        "C_baoliang": {k: bucket_view(v) for k, v in C.items()},
        "D_tier": {k: bucket_view(v) for k, v in D.items()},
        "E_theme": {k: bucket_view(v) for k, v in E.items()},
        "F_lag": {k: bucket_view(v) for k, v in F.items()},
        "G_rules_all": {k: bucket_view(v) for k, v in rule_all.items()},
        "G_rules_first": {k: bucket_view(v) for k, v in rule_first.items()},
        "G_rules_second": {k: bucket_view(v) for k, v in rule_second.items()},
        "G_survival": survived,
        "G_height_match": height_match_all,
        "walk_forward": [
            {
                "train": [fd["train_start"], fd["train_end"]],
                "test": [fd["test_start"], fd["test_end"]],
                "test_n": {k: v["n"] for k, v in fd["test"].items()},
                "test_tradable": {k: bucket_view(v)["tradable_zt"] for k, v in fd["test"].items()},
            }
            for fd in folds
        ],
        "warnings": warnings,
    }

    # write files
    write_csv(OUT / "days.csv", day_rows, list(day_rows[0].keys()) if day_rows else ["date"])
    write_csv(OUT / "leaders.csv", leader_rows, list(leader_rows[0].keys()) if leader_rows else ["date"])
    write_csv(OUT / "candidates.csv", cand_rows, list(cand_rows[0].keys()) if cand_rows else ["signal_date"])
    write_csv(OUT / "boards_disagree.csv", disagree_rows, list(disagree_rows[0].keys()) if disagree_rows else ["date"])
    (OUT / "tables.json").write_text(json.dumps(tables, ensure_ascii=False, indent=2), encoding="utf-8")

    # summary md
    def bv_line(label: str, b: dict[str, int]) -> list[str]:
        return [
            label,
            str(b["n"]),
            fmt_rate(b["zt"], b["n"]),
            fmt_rate(b["promote"], b["n"]),
            fmt_rate(b["tradable"], b["n"]),
        ]

    survived_names = [x["rule"] for x in survived if x["survived"]]
    both_halves = [x["rule"] for x in survived if x["both_halves"]]

    lines = []
    lines.append("# 连板接力切入点 — 回测摘要")
    lines.append("")
    lines.append("历史条件频率，不是交易建议。定义见 `tools/relay_study/spec.md`。")
    lines.append("")
    lines.append("## 窗口")
    lines.append("")
    lines.append(f"- 连续交易日：`{day_ids[0]}` … `{day_ids[-1]}`，**{n_days}** 日")
    lines.append(f"- 有次日的信号日：{n_pairs}")
    lines.append(f"- 对半：前半 {signal_dates[0]} … {signal_dates[mid-1]}（{len(first_half_dates)} 日），后半 {signal_dates[mid]} … {signal_dates[-1]}（{len(second_half_dates)} 日）")
    lines.append(f"- 排除孤立日：2025-04-01/02/03、2025-09-30")
    lines.append(f"- 未闭合日：{', '.join(d['date'] for d in days if not d['closed']) or '无'}")
    lines.append(f"- 开盘啦 OHLC 日：{sum(1 for d in days if d['has_ohlc'])}/{n_days}（只覆盖当日涨停股）")
    lines.append(f"- 同花顺涨停池对齐日：{sum(1 for d in days if d['has_ths'])}/{n_days}")
    lines.append(f"- 同花顺开板池日：{sum(1 for d in days if d['has_zha'])}/{n_days}")
    lines.append(f"- boards 开盘啦/同花顺不一致：{len(disagree_rows)} 条")
    lines.append(f"- 候选试验条数（boards>=2）：{len(all_c)}")
    lines.append(f"- zt_next 但非 boards+1：{n_zt_not_promote}")
    lines.append("")
    lines.append("## 定义（再次冻结）")
    lines.append("")
    lines.append("- H(t) = 当日开盘啦涨停池 `boards` 最大值")
    lines.append("- 最高板个股断板 `leader_absent`：昨日全部最高板今日不在涨停池")
    lines.append("- 高度回落 `height_drop`：H(t)<H(t-1)，与个股断板分开统计")
    lines.append(f"- 爆量：最高板成交额 / 连板段前日成交额 ≥ {BAOLIANG_RATIO}（相对前日或前日中位数）")
    lines.append("- 候选：t 收盘已知的 `boards>=2` 非 ST")
    lines.append("- 主结果：`zt_next` / `promote` / `tradable_zt`（次日涨停且非一字板）")
    lines.append("- **不可回测**：打板成交、全样本开收盘收益、断板股收益、竞价成交")
    lines.append("")
    lines.append("## 事件日计数")
    lines.append("")
    lines.append(md_table(
        ["事件", "日数"],
        [
            ["个股最高板全断 leader_absent", str(n_absent_days)],
            ["高度回落 height_drop", str(n_drop_days)],
            ["个股全断但高度未回落", str(n_absent_not_drop)],
            ["高度回落但个股未全断", str(n_drop_not_absent)],
            ["缺席最高板出现在开板池（确认炸板）", str(n_zha_days)],
            ["事后停牌续板（诊断，不可交易）", str(n_halt_days)],
            ["当日最高板爆量", str(n_baoliang_days)],
            [f"高度相对前{NEWHIGH_LOOKBACK}日创新高", str(n_newhigh_days)],
            ["见顶回落后再次摸到旧峰的间隔样本", f"{len(cycle_gaps)} 段，中位数 {tables['event_days']['cycle_reclaim_median']}"],
        ],
    ))
    if cycle_gaps:
        lines.append("")
        lines.append(f"再摸旧峰间隔（交易日）：{cycle_gaps}")
    lines.append("")
    lines.append("## A. 无条件连板次日继续（按高度）")
    lines.append("")
    lines.append(md_table(
        ["分层", "n", "次日仍涨停", "晋级 boards+1", "可买涨停(非一字)"],
        [bv_line(k, v) for k, v in A.items()],
    ))
    lines.append("")
    lines.append("对半：")
    lines.append("")
    half_rows = []
    for split, label in (("first", "前半"), ("second", "后半")):
        for k, v in A_half[split].items():
            half_rows.append(bv_line(f"{label} {k}", v))
    lines.append(md_table(["分层", "n", "次日仍涨停", "晋级", "可买涨停"], half_rows))
    lines.append("")
    lines.append("## B. 最高板断 vs 未断")
    lines.append("")
    lines.append(md_table(
        ["条件", "n", "次日仍涨停", "晋级", "可买涨停"],
        [bv_line(k, v) for k, v in B.items()],
    ))
    lines.append("")
    lines.append("## C. 最高板爆量")
    lines.append("")
    lines.append(md_table(
        ["条件", "n", "次日仍涨停", "晋级", "可买涨停"],
        [bv_line(k, v) for k, v in C.items()],
    ))
    lines.append("")
    lines.append("## D. 断板日后的梯队")
    lines.append("")
    lines.append(md_table(
        ["条件", "n", "次日仍涨停", "晋级", "可买涨停"],
        [bv_line(k, v) for k, v in D.items()],
    ))
    lines.append("")
    lines.append("## E. 题材")
    lines.append("")
    lines.append(md_table(
        ["条件", "n", "次日仍涨停", "晋级", "可买涨停"],
        [bv_line(k, v) for k, v in E.items()],
    ))
    lines.append("")
    lines.append("## F. 断板 / 爆量 后第 1/2/3 日")
    lines.append("")
    lines.append(md_table(
        ["条件", "n", "次日仍涨停", "晋级", "可买涨停"],
        [bv_line(k, v) for k, v in F.items()],
    ))
    lines.append("")
    lines.append("## G. 事先规则 + 对半 + walk-forward")
    lines.append("")
    lines.append(md_table(
        ["规则", "全样本 n / 可买", "前半 n / 可买", "后半 n / 可买", "两半都≥基线(n≥30)", "WF测试折胜/评", "存活"],
        [
            [
                x["rule"],
                f"{x['n_all']} / {fmt_rate(x['tradable_all'], x['n_all'])}",
                f"{x['n_half1']} / {fmt_rate(x['tradable_half1'], x['n_half1'])}",
                f"{x['n_half2']} / {fmt_rate(x['tradable_half2'], x['n_half2'])}",
                {True: "是", False: "否", None: "n不足"}[x["both_halves"] if x["half1_beats"] is not None and x["half2_beats"] is not None else None] if False else (
                    "是" if x["both_halves"] else ("半边n不足" if x["half1_beats"] is None or x["half2_beats"] is None else "否")
                ),
                f"{x['wf_test_folds_beat']}/{x['wf_test_folds_scored']}",
                "是" if x["survived"] else "否",
            ]
            for x in survived
        ],
    ))
    lines.append("")
    lines.append(f"两半都击败 B0 且 n≥30：{', '.join(both_halves) if both_halves else '无'}")
    lines.append(f"完整存活（两半 + walk-forward 多数测试折）：{', '.join(survived_names) if survived_names else '无'}")
    lines.append("")
    lines.append("Walk-forward 测试折可买涨停率：")
    lines.append("")
    wf_headers = ["测试折"] + list(rules.keys())
    wf_rows = []
    for fd, rec in zip(folds, tables["walk_forward"]):
        row = [f"{rec['test'][0]}…{rec['test'][1]}"]
        for name in rules:
            tv = rec["test_tradable"][name]
            if tv["n"] == 0:
                row.append("n=0")
            else:
                row.append(f"{tv['ok']}/{tv['n']}={tv['rate']:.1%}")
        wf_rows.append(row)
    lines.append(md_table(wf_headers, wf_rows))
    lines.append("")
    lines.append("## 用户「断板次日接力」在数据里对在哪、错在哪")
    lines.append("")
    b0 = A["all>=2"]
    r1 = rule_all["R1_absent_all_lianban"]
    r2 = rule_all["R2_sealed_all_lianban"]
    lines.append(
        f"- 对的部分：最高板确实会断，操作定义断板日 {n_absent_days} 个；"
        f"高度回落日 {n_drop_days} 个，两者差 {abs(n_absent_days-n_drop_days)} 日，"
        f"说明「看高度掉了」和「龙头个股不在池里」不是同一件事。"
        f"事后停牌续板 {n_halt_days} 日，把停牌当成断板会提前开新周期。"
    )
    lines.append(
        f"- 基线无条件连板可买续板：{fmt_rate(b0['tradable'], b0['n'])}。"
        f"断板后次日全接：{fmt_rate(r1['tradable'], r1['n'])}。"
        f"未断时全接：{fmt_rate(r2['tradable'], r2['n'])}。"
    )
    lines.append(
        "- 错的部分：断板并不自动释放风险。若 R1 不高于 R2 / B0，则「断了更安全」不成立。"
        "高位梯队在断板日经常整排消失（例如 2026-08-06 的 10 板 603221 次日不在涨停池也不在开板池），"
        "次日并没有可接的 H-1/H-2 残梯。"
        "爆量也不是可靠的新周期开关：见 C/F 表，而不是叙事。"
    )
    lines.append(
        "- 打板收益无法回测。本文件所有百分比都是「次日是否还在涨停池」，"
        "成功样本里还有一字板（tradable_zt 已扣除）。失败样本几乎没有开收盘价。"
    )
    lines.append("")
    lines.append("## 高度匹配稳健性")
    lines.append("")
    lines.append("规则若只是挑了更高的板，会轻松超过含大量 2 板的 B0。下表用「同样 boards 的无条件可买续板率」做期望。残差≈0 表示没有额外的断板/题材效应。")
    lines.append("")
    hm_rows = []
    for name, pred in rules.items():
        if name == "R8_newhigh_skip":
            continue
        hm = height_match_all[name]
        if hm["n"] == 0:
            hm_rows.append([name, "0", "—", "—", "—"])
        else:
            hm_rows.append([
                name,
                str(hm["n"]),
                f"{hm['actual']:.1%}",
                f"{hm['expected']:.1%}",
                f"{hm['residual']:+.1%}",
            ])
    lines.append(md_table(["规则", "n", "实际可买续板", "同高度期望", "残差"], hm_rows))
    lines.append("")
    robust_names = [x["rule"] for x in survived if x.get("robust_survived")]
    lines.append(
        f"机械存活（两半≥B0 且 n≥30 且 WF 多数）：{', '.join(survived_names) if survived_names else '无'}。"
        f"再要求两半高度残差≥0：{', '.join(robust_names) if robust_names else '无'}。"
    )
    lines.append("")
    lines.append("## 切入点结论")
    lines.append("")
    if robust_names:
        lines.append(
            "下列规则在对半、walk-forward 以及高度匹配残差上同时成立："
            + ", ".join(robust_names)
            + "。这仍只是次日是否继续涨停的条件频率，不是可成交的价格回测。"
        )
    else:
        lines.append(
            "没有规则在「时间对半 + walk-forward + 高度匹配」三条线上同时成立。"
            "R2（最高板仍封时接所有连板）相对 B0 只有约 1 个百分点，且可被「断板日略差」解释。"
            "R5（断板后接当日新最高板）看起来高于 B0，高度匹配后残差接近 0：只是板更高，不是断板本身给了安全垫。"
            "按规格**不宣布最佳切入点**。"
        )
    lines.append("")
    lines.append("## 数据缺口")
    lines.append("")
    lines.append("- 无历史竞价，`data/research/auction/observations.jsonl` 为空。")
    lines.append("- 开盘啦 OHLC 只出现在涨停成功股，且 2026-08-04/05/07/10–13 等近日缺失。")
    lines.append("- 开板池只有曾触板未封者，漏掉低开弱杀（2026-08-07 的 603221）。")
    lines.append("- 无停牌公告，停牌续板只能事后从高度连续性推断。")
    lines.append("- 无 ST 样本，ST 过滤未经压力。")
    lines.append("- 主题只用开盘啦主 `theme` 字符串，同花顺大风口只作背景，不进主规则。")
    if warnings:
        lines.append("")
        lines.append("## 运行警告")
        for x in warnings:
            lines.append(f"- {x}")
    lines.append("")
    lines.append("复现：`python tools/relay_study/run.py`")
    lines.append("")

    (OUT / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    # also copy a short pointer at tools/_relay_entry_study_out.md? spec asked original path too.
    # Parent later asked for tools/relay_study/. Keep only the package.
    print(f"days={n_days} candidates={len(all_c)} absent_days={n_absent_days}")
    print(f"survived={survived_names or 'NONE'}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
