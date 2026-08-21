# -*- coding: utf-8 -*-
"""Buyable-path hunt + new relay event frequencies.

Stdlib only. Does not modify ultraboard/ or data contracts.
Writes tools/relay_study/out/buyable_hunt.md and supporting csv.
"""
from __future__ import annotations

import csv
import json
import datetime
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
OUT = STUDY / "out"
RAW = ROOT / "data" / "kaipanla" / "raw"
THS_ZT = ROOT / "data" / "ths" / "limit_pool"
THS_ZHA = ROOT / "data" / "ths" / "open_limit_pool"
BAR_DIR = OUT / "daily_bars"
AUCTION = ROOT / "data" / "research" / "auction" / "observations.jsonl"

MIN_CLAIM = 30
MIN_HALF = 15
TARGET = 0.90
WINDOW_START = "2025-10-09"
WINDOW_END = "2026-08-12"


def _f(v):
    if v in (None, ""):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _i(v):
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _b(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    return None


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def limit_pct(code):
    c = str(code)
    if c.startswith(("300", "301", "688")):
        return 20.0
    return 10.0


def limit_up(prev_close, pct):
    if prev_close is None or prev_close <= 0:
        return None
    return round(prev_close * (1.0 + pct / 100.0), 2)


def near(a, b, tol=0.011):
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def load_candidates():
    with (OUT / "candidates.csv").open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_days():
    with (OUT / "days.csv").open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_bars():
    bars = {}
    if not BAR_DIR.exists():
        return bars
    for p in BAR_DIR.glob("*.json"):
        try:
            doc = _read_json(p)
        except Exception:
            continue
        code = str(doc.get("code") or p.stem)
        bars[code] = doc.get("bars") or {}
    return bars


def hunt_coverage(cands, bars):
    raw_days = sorted(
        d.name for d in RAW.iterdir()
        if d.is_dir() and (d / "zt_pool.json").exists()
    )
    win = [d for d in raw_days if WINDOW_START <= d <= "2026-08-13"]
    n_open = n_price = n_high = 0
    n_stocks = 0
    days_any_open = 0
    for day in win:
        doc = _read_json(RAW / day / "zt_pool.json")
        stocks = doc.get("stocks") or []
        n_stocks += len(stocks)
        any_open = False
        for s in stocks:
            if s.get("price") not in (None, ""):
                n_price += 1
            if s.get("open") not in (None, ""):
                n_open += 1
                any_open = True
            if s.get("high") not in (None, ""):
                n_high += 1
        if any_open:
            days_any_open += 1
    ths_days = sorted(p.stem for p in THS_ZT.glob("*.json"))
    zha_days = sorted(p.stem for p in THS_ZHA.glob("*.json"))
    auction_size = AUCTION.stat().st_size if AUCTION.exists() else 0
    n_bar_codes = len(bars)
    n_bar_need = len({r["code"] for r in cands})
    # candidate next-day print coverage
    n = len(cands)
    n_zt = sum(1 for r in cands if _b(r["zt_next"]))
    n_zha = sum(1 for r in cands if _b(r["zha_next"]))
    n_neither = sum(1 for r in cands if not _b(r["zt_next"]) and not _b(r["zha_next"]))
    n_zha_cr = sum(1 for r in cands if r.get("zha_change_rate") not in (None, ""))
    # bar join
    n_t_bar = 0
    n_n1_bar = 0
    n_fail_n1 = 0
    n_fail_n1_bar = 0
    n_seal_n1_bar = 0
    for r in cands:
        bmap = bars.get(r["code"]) or {}
        if r["signal_date"] in bmap:
            n_t_bar += 1
        if r["outcome_date"] in bmap:
            n_n1_bar += 1
            if _b(r["zt_next"]):
                n_seal_n1_bar += 1
            else:
                n_fail_n1_bar += 1
        if not _b(r["zt_next"]):
            n_fail_n1 += 1
    return {
        "raw_days_all": len(raw_days),
        "raw_days_window": len(win),
        "window_first": win[0] if win else None,
        "window_last": win[-1] if win else None,
        "zt_stocks_window": n_stocks,
        "zt_price": n_price,
        "zt_open": n_open,
        "zt_high": n_high,
        "days_any_open": days_any_open,
        "ths_zt_days": len(ths_days),
        "ths_zha_days": len(zha_days),
        "auction_bytes": auction_size,
        "cand_n": n,
        "cand_zt_next": n_zt,
        "cand_zha_next": n_zha,
        "cand_neither": n_neither,
        "cand_zha_cr": n_zha_cr,
        "bar_codes": n_bar_codes,
        "bar_need": n_bar_need,
        "cand_t_bar": n_t_bar,
        "cand_n1_bar": n_n1_bar,
        "fail_n": n_fail_n1,
        "fail_n1_bar": n_fail_n1_bar,
        "seal_n1_bar": n_seal_n1_bar,
    }


def attach_features(cands, days, bars):
    day_by = {d["date"]: d for d in days}
    dates = sorted({r["signal_date"] for r in cands})
    # same-day extras
    extras = {}
    theme_n = {}
    theme_codes = defaultdict(list)
    for day in dates:
        pool_path = RAW / day / "zt_pool.json"
        ths_path = THS_ZT / (day + ".json")
        stocks = []
        if pool_path.exists():
            stocks = _read_json(pool_path).get("stocks") or []
        ths = {}
        if ths_path.exists():
            ths = {str(s.get("code")): s for s in (_read_json(ths_path).get("stocks") or []) if s.get("code")}
        tc = Counter()
        for s in stocks:
            th = str(s.get("theme") or "").strip()
            code = str(s.get("code") or "")
            if th:
                tc[th] += 1
                theme_codes[(day, th)].append(code)
            if not code:
                continue
            t = ths.get(code) or {}
            extras[(day, code)] = {
                "amount": _f(s.get("amount")),
                "turnover": _f(s.get("turnover_rate")),
                "price": _f(s.get("price")),
                "is_fanbao": bool(s.get("is_fanbao")),
                "open_count": _i(t.get("open_count")),
                "board_type": t.get("board_type") or "",
                "one_price": bool(t.get("one_price")) if t else None,
                "seal_ratio": _f(t.get("seal_order_ratio")),
                "suc_rate": _f(t.get("limit_up_success_rate")),
                "first_limit_ts": _i(t.get("first_limit_ts")),
                "circ": _f(t.get("circulating_market_cap")),
            }
        for th, n in tc.items():
            theme_n[(day, th)] = n

    # next trading day map from candidates
    next_of = {}
    for r in cands:
        next_of[r["signal_date"]] = r["outcome_date"]
    # also from days.csv order
    day_order = [d["date"] for d in days]
    pos = {d: i for i, d in enumerate(day_order)}

    rows = []
    for r in cands:
        ex = extras.get((r["signal_date"], r["code"])) or {}
        boards = _i(r["boards"]) or 0
        one_t = _b(r["one_price_today"])
        zt1 = bool(_b(r["zt_next"]))
        zha1 = bool(_b(r["zha_next"]))
        zha_cr = _f(r.get("zha_change_rate"))
        zt2 = _b(r.get("zt_d2"))
        zt3 = _b(r.get("zt_d3"))
        one_n = _b(r.get("one_word_next"))
        theme = (r.get("theme") or "").strip()
        t = r["signal_date"]
        u1 = r["outcome_date"]
        i = pos.get(t)
        u2 = day_order[i + 2] if i is not None and i + 2 < len(day_order) else None
        u3 = day_order[i + 3] if i is not None and i + 3 < len(day_order) else None
        bmap = bars.get(r["code"]) or {}
        bar_t = bmap.get(t)
        bar1 = bmap.get(u1)
        bar2 = bmap.get(u2) if u2 else None
        bar3 = bmap.get(u3) if u3 else None
        px_t = ex.get("price")
        if px_t is None and bar_t:
            px_t = _f(bar_t.get("c"))
        lp = limit_pct(r["code"])
        lim1 = limit_up(px_t, lp)
        open1 = _f(bar1.get("o")) if bar1 else None
        high1 = _f(bar1.get("h")) if bar1 else None
        low1 = _f(bar1.get("l")) if bar1 else None
        close1 = _f(bar1.get("c")) if bar1 else None
        yizi_open1 = False
        if open1 is not None and lim1 is not None:
            yizi_open1 = near(open1, lim1) and (high1 is None or near(high1, lim1)) and (low1 is None or near(low1, lim1))
        if one_n is True and open1 is not None and close1 is not None and near(open1, close1):
            yizi_open1 = True
        # outcomes
        zt_3d = bool(zt1 or zt2 or zt3)
        cons_not_lose = bool(zt1 or (zha1 and zha_cr is not None and zha_cr > 0))
        has_print = bool(zt1 or zha1)
        print_not_lose = None
        if has_print:
            print_not_lose = bool(zt1 or (zha_cr is not None and zha_cr > 0))
        hold_close = None
        if px_t is not None and close1 is not None:
            hold_close = close1 > px_t
        hold_not_lose = None
        if px_t is not None and close1 is not None:
            hold_not_lose = close1 >= px_t * 0.999
        open_follow = None
        buyable_open = False
        if open1 is not None and close1 is not None and not yizi_open1:
            buyable_open = True
            open_follow = close1 > open1
        open_follow_flat = None
        if buyable_open:
            open_follow_flat = close1 >= open1 * 0.999
        # 3d touch limit after a fill at t+1 open
        touch3 = None
        if buyable_open:
            hits = []
            prev = px_t
            for bar in (bar1, bar2, bar3):
                if not bar or prev is None:
                    hits.append(False)
                    continue
                lim = limit_up(prev, lp)
                h = _f(bar.get("h"))
                c = _f(bar.get("c"))
                hits.append(bool(lim and h is not None and h >= lim - 0.011))
                if c is not None:
                    prev = c
            touch3 = any(hits)
        open_then_zt3 = None
        if buyable_open:
            open_then_zt3 = zt_3d
        hold_then_zt3 = None
        if one_t is False:
            hold_then_zt3 = zt_3d
        hold_touch3 = None
        if one_t is False and px_t is not None and (bar1 or bar2 or bar3):
            hits = []
            prev = px_t
            for bar in (bar1, bar2, bar3):
                if not bar or prev is None:
                    hits.append(False)
                    continue
                lim = limit_up(prev, lp)
                h = _f(bar.get("h"))
                c = _f(bar.get("c"))
                hits.append(bool(lim and h is not None and h >= lim - 0.011))
                if c is not None:
                    prev = c
            hold_touch3 = any(hits)
        hold_3d = None
        close3 = _f(bar3.get("c")) if bar3 else None
        close2 = _f(bar2.get("c")) if bar2 else None
        if px_t is not None and close3 is not None:
            hold_3d = close3 > px_t
        open_3d = None
        if buyable_open and close3 is not None:
            open_3d = close3 > open1
        maxclose3 = None
        if px_t is not None:
            cs = [c for c in (close1, close2, close3) if c is not None]
            if cs:
                maxclose3 = max(cs) > px_t
        own_theme_n = theme_n.get((t, theme), 0)
        rec = dict(r)
        rec.update({
            "one_t": one_t,
            "boards_i": boards,
            "amount": ex.get("amount"),
            "turnover": ex.get("turnover"),
            "is_fanbao": ex.get("is_fanbao"),
            "open_count": ex.get("open_count"),
            "own_theme_n": own_theme_n,
            "theme_alive_own": own_theme_n >= 2,
            "px_t": px_t,
            "open1": open1,
            "high1": high1,
            "close1": close1,
            "yizi_open1": yizi_open1,
            "has_bar1": bar1 is not None,
            "zt_3d": zt_3d,
            "cons_not_lose": cons_not_lose,
            "has_print": has_print,
            "print_not_lose": print_not_lose,
            "hold_close": hold_close,
            "hold_not_lose": hold_not_lose,
            "buyable_open": buyable_open,
            "open_follow": open_follow,
            "open_follow_flat": open_follow_flat,
            "touch3": touch3,
            "open_then_zt3": open_then_zt3,
            "hold_then_zt3": hold_then_zt3,
            "hold_touch3": hold_touch3,
            "hold_3d": hold_3d,
            "open_3d": open_3d,
            "maxclose3": maxclose3,
            "leader_absent_b": bool(_b(r["leader_absent"])),
            "height_drop_b": bool(_b(r["height_drop"])),
            "theme_alive_b": bool(_b(r["theme_alive"])),
            "same_theme_b": bool(_b(r["same_theme_broken"])),
            "is_new_high_b": bool(_b(r["is_new_high"])),
            "is_sub_high_b": bool(_b(r["is_sub_high"])),
            "is_mid_b": bool(_b(r["is_mid_2_3"])),
            "leader_baoliang_b": bool(_b(r["leader_baoliang"])),
            "prev_leader_baoliang_b": bool(_b(r["prev_leader_baoliang"])),
            "seal_ratio": ex.get("seal_ratio"),
            "suc_rate": ex.get("suc_rate"),
            "circ": ex.get("circ"),
            "strong_seal": (ex.get("seal_ratio") is not None and ex.get("seal_ratio") >= 0.02),
            "early_seal": False,
        })
        ts = ex.get("first_limit_ts")
        if ts:
            hr = datetime.datetime.fromtimestamp(int(ts), datetime.timezone(datetime.timedelta(hours=8))).hour
            rec["early_seal"] = hr < 10
        rows.append(rec)
    return rows, theme_n, next_of, day_order


def halves(rows):
    dates = sorted({r["signal_date"] for r in rows})
    mid = len(dates) // 2
    return set(dates[:mid]), set(dates[mid:]), dates


def rate_of(rows, pred, outcome_key, require_not_none=True):
    sel = [r for r in rows if pred(r)]
    used = []
    for r in sel:
        v = r.get(outcome_key)
        if v is None and require_not_none:
            continue
        used.append(bool(v))
    n = len(used)
    w = sum(used)
    return w, n, (w / n if n else None), len(sel)


def cell_view(rows, pred, outcome_key, first, second):
    w, n, rt, n_sel = rate_of(rows, pred, outcome_key)
    w1, n1, r1, _ = rate_of(rows, lambda r: pred(r) and r["signal_date"] in first, outcome_key)
    w2, n2, r2, _ = rate_of(rows, lambda r: pred(r) and r["signal_date"] in second, outcome_key)
    claim = (
        n >= MIN_CLAIM
        and rt is not None and rt >= TARGET
        and n1 >= MIN_HALF and r1 is not None and r1 >= TARGET
        and n2 >= MIN_HALF and r2 is not None and r2 >= TARGET
    )
    return {
        "wins": w, "n": n, "rate": rt, "n_sel": n_sel,
        "h1_w": w1, "h1_n": n1, "h1": r1,
        "h2_w": w2, "h2_n": n2, "h2": r2,
        "claim": claim,
    }


def fmt_rate(w, n, rt):
    if n <= 0 or rt is None:
        return "n=0"
    return "%d/%d = %.1f%%" % (w, n, 100.0 * rt)


def theme_persistence(cands, theme_n, day_order):
    # theme-day events, selection uses t only
    pos = {d: i for i, d in enumerate(day_order)}
    # collect themes per day from candidates + theme_n keys
    days = sorted({r["signal_date"] for r in cands})
    out = []
    seen = set()
    for (day, theme), n in theme_n.items():
        if day not in pos:
            continue
        i = pos[day]
        if i + 1 >= len(day_order):
            continue
        nxt = day_order[i + 1]
        n1 = theme_n.get((nxt, theme), 0)
        out.append({"date": day, "theme": theme, "n_t": n, "n_next": n1})
        seen.add((day, theme))
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cands = load_candidates()
    days = load_days()
    bars = load_bars()
    cov = hunt_coverage(cands, bars)
    rows, theme_n, next_of, day_order = attach_features(cands, days, bars)
    first, second, date_list = halves(rows)
    buyable = [r for r in rows if r["one_t"] is False]
    print("cands", len(rows), "buyable_entry_not_yizi_t", len(buyable), "bars", len(bars), flush=True)

    outcomes = [
        ("zt_3d", "in zt_pool t+1/t+2/t+3 (membership, not a fill)", True),
        ("hold_then_zt3", "non-yizi t AND zt_3d (entry at t, membership win)", True),
        ("cons_not_lose", "zt_next OR (zha and change_rate>0); absent=loss", True),
        ("print_not_lose", "among zt-or-zha prints only: not lose vs t close", True),
        ("hold_close", "buy t close, t+1 close > t close (needs bar)", True),
        ("hold_not_lose", "buy t close, t+1 close >= t close", True),
        ("hold_touch3", "buy t close, any of t+1..t+3 high touches limit", True),
        ("open_follow", "buy t+1 open if not yizi-open, t+1 close > open", True),
        ("open_follow_flat", "buy t+1 open if not yizi-open, close >= open", True),
        ("open_then_zt3", "buy t+1 open if not yizi-open, then zt within 3d", True),
        ("touch3", "buy t+1 open if not yizi-open, 3d high touches limit", True),
        ("tradable_zt", "next-day tradable zt (old ceiling, baseline only)", True),
        ("hold_3d", "buy t close, t+3 close > t close", True),
        ("open_3d", "buy t+1 open if not yizi-open, t+3 close > open", True),
        ("maxclose3", "buy t close, max(t+1..t+3 close) > t close", True),
    ]

    named = [
        ("ALL_non_yizi_t", lambda r: r["one_t"] is False),
        ("non_yizi_2", lambda r: r["one_t"] is False and r["boards_i"] == 2),
        ("non_yizi_3", lambda r: r["one_t"] is False and r["boards_i"] == 3),
        ("non_yizi_4", lambda r: r["one_t"] is False and r["boards_i"] == 4),
        ("non_yizi_5p", lambda r: r["one_t"] is False and r["boards_i"] >= 5),
        ("non_yizi_mid23", lambda r: r["one_t"] is False and r["is_mid_b"]),
        ("non_yizi_sub_high", lambda r: r["one_t"] is False and r["is_sub_high_b"]),
        ("non_yizi_new_high", lambda r: r["one_t"] is False and r["is_new_high_b"]),
        ("break_all_non_yizi", lambda r: r["one_t"] is False and r["leader_absent_b"]),
        ("break_same_theme_non_yizi", lambda r: r["one_t"] is False and r["leader_absent_b"] and r["same_theme_b"]),
        ("break_same_theme_mid23", lambda r: r["one_t"] is False and r["leader_absent_b"] and r["same_theme_b"] and r["is_mid_b"]),
        ("break_same_theme_2", lambda r: r["one_t"] is False and r["leader_absent_b"] and r["same_theme_b"] and r["boards_i"] == 2),
        ("break_same_theme_3", lambda r: r["one_t"] is False and r["leader_absent_b"] and r["same_theme_b"] and r["boards_i"] == 3),
        ("break_mid23", lambda r: r["one_t"] is False and r["leader_absent_b"] and r["is_mid_b"]),
        ("break_new_high_non_yizi", lambda r: r["one_t"] is False and r["leader_absent_b"] and r["is_new_high_b"]),
        ("break_theme_alive_mid23", lambda r: r["one_t"] is False and r["leader_absent_b"] and r["theme_alive_b"] and r["is_mid_b"]),
        ("break_theme_alive_same_mid23", lambda r: r["one_t"] is False and r["leader_absent_b"] and r["theme_alive_b"] and r["same_theme_b"] and r["is_mid_b"]),
        ("intact_mid23", lambda r: r["one_t"] is False and (not r["leader_absent_b"]) and r["is_mid_b"]),
        ("intact_sub_high", lambda r: r["one_t"] is False and (not r["leader_absent_b"]) and r["is_sub_high_b"]),
        ("intact_new_high", lambda r: r["one_t"] is False and (not r["leader_absent_b"]) and r["is_new_high_b"]),
        ("drop_mid23", lambda r: r["one_t"] is False and r["height_drop_b"] and r["is_mid_b"]),
        ("drop_same_theme_mid23", lambda r: r["one_t"] is False and r["height_drop_b"] and r["same_theme_b"] and r["is_mid_b"]),
        ("drop_theme_alive_mid23", lambda r: r["one_t"] is False and r["height_drop_b"] and r["theme_alive_b"] and r["is_mid_b"]),
        ("intact_theme_alive_mid23", lambda r: r["one_t"] is False and (not r["leader_absent_b"]) and r["theme_alive_own"] and r["is_mid_b"]),
        ("theme_n_ge3_mid23", lambda r: r["one_t"] is False and r["own_theme_n"] >= 3 and r["is_mid_b"]),
        ("theme_n_ge4_mid23", lambda r: r["one_t"] is False and r["own_theme_n"] >= 4 and r["is_mid_b"]),
        ("theme_n_ge5_2", lambda r: r["one_t"] is False and r["own_theme_n"] >= 5 and r["boards_i"] == 2),
        ("opened_today_mid23", lambda r: r["one_t"] is False and (r["open_count"] or 0) >= 1 and r["is_mid_b"]),
        ("unopened_non_yizi_mid23", lambda r: r["one_t"] is False and r["open_count"] == 0 and r["is_mid_b"]),
        ("break_opened_mid23", lambda r: r["one_t"] is False and r["leader_absent_b"] and (r["open_count"] or 0) >= 1 and r["is_mid_b"]),
        ("amt_mid_mid23", lambda r: r["one_t"] is False and r["is_mid_b"] and r["amount"] is not None and 5e7 <= r["amount"] <= 4e8),
        ("break_amt_mid_same", lambda r: r["one_t"] is False and r["leader_absent_b"] and r["same_theme_b"] and r["is_mid_b"] and r["amount"] is not None and 5e7 <= r["amount"] <= 4e8),
        ("fail_t1_then_watch", lambda r: r["one_t"] is False and (not _b(r["zt_next"]))),
        ("fail_t1_break_mid23", lambda r: r["one_t"] is False and (not _b(r["zt_next"])) and r["leader_absent_b"] and r["is_mid_b"]),
        ("strong_seal_ny", lambda r: r["one_t"] is False and r.get("strong_seal")),
        ("strong_seal_ge3", lambda r: r["one_t"] is False and r.get("strong_seal") and r["boards_i"] >= 3),
        ("strong_seal_ge4", lambda r: r["one_t"] is False and r.get("strong_seal") and r["boards_i"] >= 4),
        ("early_ge4", lambda r: r["one_t"] is False and r.get("early_seal") and r["boards_i"] >= 4),
        ("early_ge5", lambda r: r["one_t"] is False and r.get("early_seal") and r["boards_i"] >= 5),
        ("early_3", lambda r: r["one_t"] is False and r.get("early_seal") and r["boards_i"] == 3),
        ("strong_seal_early_ge3", lambda r: r["one_t"] is False and r.get("strong_seal") and r.get("early_seal") and r["boards_i"] >= 3),
        ("theme8_mid23", lambda r: r["one_t"] is False and r["own_theme_n"] >= 8 and r["is_mid_b"]),
        ("theme8_ge3", lambda r: r["one_t"] is False and r["own_theme_n"] >= 8 and r["boards_i"] >= 3),
        ("theme8_3", lambda r: r["one_t"] is False and r["own_theme_n"] >= 8 and r["boards_i"] == 3),
        ("theme10_any", lambda r: r["one_t"] is False and r["own_theme_n"] >= 10),
        ("suc80_ge3", lambda r: r["one_t"] is False and r.get("suc_rate") is not None and r["suc_rate"] >= 0.8 and r["boards_i"] >= 3),
        ("intact_strong_ge3", lambda r: r["one_t"] is False and (not r["leader_absent_b"]) and r.get("strong_seal") and r["boards_i"] >= 3),
        ("circ_mid_ge3", lambda r: r["one_t"] is False and r["boards_i"] >= 3 and r.get("circ") is not None and 3e9 <= r["circ"] <= 2e10),
    ]

    # fail_t1 uses t+1 zt which is look-ahead if used as selection for a t entry.
    # Keep those two as DIAGNOSTIC only (labeled).
    diagnostic = {"fail_t1_then_watch", "fail_t1_break_mid23"}

    cells = []
    claims = []
    for ev_name, pred in named:
        for ok, desc, _ in outcomes:
            # skip look-ahead selections for claim outcomes except as notes
            cv = cell_view(rows, pred, ok, first, second)
            rec = {
                "event": ev_name,
                "outcome": ok,
                "desc": desc,
                "lookahead_sel": ev_name in diagnostic,
                **cv,
            }
            cells.append(rec)

    def r_ok_buyable(ok):
        return ok in {
            "hold_close", "hold_not_lose", "hold_touch3",
            "open_follow", "open_follow_flat", "open_then_zt3", "touch3",
            "cons_not_lose", "hold_3d", "open_3d", "maxclose3",
        }

    # fix claims with proper helper (defined after loop by filtering)
    claims = [
        c for c in cells
        if c["claim"] and not c["lookahead_sel"] and c["outcome"] in {
            "hold_close", "hold_not_lose", "hold_touch3",
            "open_follow", "open_follow_flat", "open_then_zt3", "touch3",
            "cons_not_lose", "hold_3d", "open_3d", "maxclose3",
        }
    ]
    membership_hot = [
        c for c in cells
        if c["claim"] and not c["lookahead_sel"] and c["outcome"] in {"zt_3d", "hold_then_zt3"}
    ]

    # theme persistence
    themes = theme_persistence(cands, theme_n, day_order)
    theme_rows = []
    for min_n, need_next in ((2, 1), (3, 1), (3, 2), (4, 1), (4, 2), (5, 1), (5, 2), (5, 3), (6, 1), (8, 1), (8, 2), (10, 1), (10, 2), (12, 1), (15, 1)):
        pred = [x for x in themes if x["n_t"] >= min_n]
        w = sum(1 for x in pred if x["n_next"] >= need_next)
        n = len(pred)
        # halves by date
        dset = sorted({x["date"] for x in pred})
        mid = len(dset) // 2
        fset, sset = set(dset[:mid]), set(dset[mid:])
        p1 = [x for x in pred if x["date"] in fset]
        p2 = [x for x in pred if x["date"] in sset]
        w1 = sum(1 for x in p1 if x["n_next"] >= need_next)
        w2 = sum(1 for x in p2 if x["n_next"] >= need_next)
        theme_rows.append({
            "rule": "theme_n>=%d and next>=%d" % (min_n, need_next),
            "n": n, "wins": w, "rate": (w / n if n else None),
            "h1_n": len(p1), "h1_w": w1, "h1": (w1 / len(p1) if p1 else None),
            "h2_n": len(p2), "h2_w": w2, "h2": (w2 / len(p2) if p2 else None),
        })

    # missing quote list
    missing = []
    for r in rows:
        if r["has_bar1"]:
            continue
        missing.append({
            "signal_date": r["signal_date"],
            "outcome_date": r["outcome_date"],
            "code": r["code"],
            "name": r["name"],
            "boards": r["boards"],
            "zt_next": r["zt_next"],
            "zha_next": r["zha_next"],
            "zha_change_rate": r.get("zha_change_rate"),
        })

    # write csvs
    cell_fields = [
        "event", "outcome", "lookahead_sel", "n", "wins", "rate", "n_sel",
        "h1_n", "h1_w", "h1", "h2_n", "h2_w", "h2", "claim", "desc",
    ]
    with (OUT / "buyable_cells.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cell_fields, extrasaction="ignore")
        w.writeheader()
        for c in cells:
            row = dict(c)
            if row.get("rate") is not None:
                row["rate"] = "%.4f" % row["rate"]
            if row.get("h1") is not None:
                row["h1"] = "%.4f" % row["h1"]
            if row.get("h2") is not None:
                row["h2"] = "%.4f" % row["h2"]
            w.writerow(row)
    with (OUT / "missing_next_bars.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(missing[0].keys()) if missing else [
            "signal_date", "outcome_date", "code", "name", "boards", "zt_next", "zha_next", "zha_change_rate"
        ])
        w.writeheader()
        for m in missing:
            w.writerow(m)
    with (OUT / "theme_persist.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["rule", "n", "wins", "rate", "h1_n", "h1_w", "h1", "h2_n", "h2_w", "h2"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for tr in theme_rows:
            row = dict(tr)
            for k in ("rate", "h1", "h2"):
                if row.get(k) is not None:
                    row[k] = "%.4f" % row[k]
            w.writerow(row)

    # best buyable cells per outcome
    def best_for(ok, min_n=30):
        pool = [
            c for c in cells
            if c["outcome"] == ok and not c["lookahead_sel"] and c["n"] >= min_n
        ]
        pool.sort(key=lambda c: (-(c["rate"] or 0), -c["n"]))
        return pool[:8]

    md = []
    md.append("# Buyable-path hunt")
    md.append("")
    md.append("Date: 2026-08-17. Historical frequencies only. Not a trading scheme.")
    md.append("Win-rate bar remains 90% on BUYABLE fills. 一字 continuation is discarded, not optimized.")
    md.append("")
    md.append("## 1. Price / volume path coverage")
    md.append("")
    md.append("Hunted: `data/kaipanla/raw/*/zt_pool.json`, `data/ths/limit_pool`, `data/ths/open_limit_pool`,")
    md.append("`data/ths/stories` (narrative only), `data/research/auction/observations.jsonl` (empty),")
    md.append("`data/research/node_pools` (README only),")
    md.append("parquet/csv/jsonl caches (none outside relay_study/out), kaipanla sentiment/expression/sector_ladder")
    md.append("(market / theme structure, no individual fail-day OHLC).")
    md.append("")
    md.append("| path | coverage | usable for fail-day prices? |")
    md.append("| --- | --- | --- |")
    md.append("| kaipanla zt_pool price (close) | %d/%d window stocks | only names that sealed that day |" % (cov["zt_price"], cov["zt_stocks_window"]))
    md.append("| kaipanla zt_pool open/high/low | %d fields, %d/%d days have any | almost only yesterday-seal continuations; 0 fail-day opens |" % (cov["zt_open"], cov["days_any_open"], cov["raw_days_window"]))
    md.append("| THS limit_pool price/change_rate/one_price | %d days | seal-day only |" % cov["ths_zt_days"])
    md.append("| THS open_limit_pool (炸板) price+change_rate | %d days | YES as t+1 fail print if they touched limit |" % cov["ths_zha_days"])
    md.append("| auction observations | %d bytes | no |" % cov["auction_bytes"])
    md.append("| THS v6 line last3600 (this hunt) | %d/%d candidate codes cached |" % (cov["bar_codes"], cov["bar_need"]))
    md.append("")
    md.append("Candidate rows (boards>=2, %s..%s): **n=%d**." % (WINDOW_START, WINDOW_END, cov["cand_n"]))
    md.append("")
    md.append("| t+1 fate | n | price we already had |")
    md.append("| --- | --- | --- |")
    md.append("| in zt_pool | %d | seal close; open only if enriched (success-only) |" % cov["cand_zt_next"])
    md.append("| in 炸板池 (change_rate) | %d | t+1 close vs t close |" % cov["cand_zha_next"])
    md.append("| neither | %d | **none** until daily bars |" % cov["cand_neither"])
    md.append("")
    md.append("Daily-bar join (THS last3600, 连板 universe only): t bar %d/%d, t+1 bar %d/%d, fail t+1 bar %d/%d." % (
        cov["cand_t_bar"], cov["cand_n"], cov["cand_n1_bar"], cov["cand_n"], cov["fail_n1_bar"], cov["fail_n"]
    ))
    md.append("Missing t+1 bars listed in `out/missing_next_bars.csv` (n=%d)." % len(missing))
    md.append("")
    md.append("Unused downloader: `KaipanlaClient.his_daban_list` is not in the backfill contract and was not blasted.")
    md.append("`ultraboard.ths.limit_pool.STOCK_LINE_ENDPOINT` already fetches the same K-line and discards OHLC;")
    md.append("this hunt reuses that endpoint for the 1109-code 连板 universe only, cached under `out/daily_bars/`.")
    md.append("")
    md.append("## 2. Entry / win definitions (new; not the old tradable_zt grid)")
    md.append("")
    md.append("Entry (t-known): name is in t 涨停池, boards>=2, **not 一字 on t**. That is the only entry set.")
    md.append("Fills:")
    md.append("")
    md.append("- `hold_*`: assume a human could have bought during t (non-一字). Mark at t close.")
    md.append("- `open_*`: buy t+1 open **only if t+1 open is not a limit/一字 open**. If 一字 open, no fill (excluded from that denominator).")
    md.append("")
    md.append("Wins:")
    md.append("")
    for ok, desc, _ in outcomes:
        md.append("- `%s`: %s" % (ok, desc))
    md.append("")
    md.append("`zt_3d` / `hold_then_zt3` are membership, not fills. They are reported, not claimed as 90% buyable.")
    md.append("`print_not_lose` drops the 1461 no-print names — selection bias, diagnostic only.")
    md.append("`tradable_zt` is the old ceiling (~25–37%); not re-mined as a scheme.")
    md.append("")
    md.append("Claim bar (buyable fills only): n>=30, full-sample >=90%, both time halves n>=15 and >=90%.")
    md.append("Halves: first %s..%s / second %s..%s." % (
        min(first), max(first), min(second), max(second)
    ))
    md.append("")
    md.append("## 3. Claimed 90% buyable cells")
    md.append("")
    if not claims:
        md.append("**None.** No new event × fill-win cell hit 90% on both halves with n>=30.")
    else:
        md.append("These met the numeric bar. Still frequencies, not a scheme.")
        md.append("")
        md.append("| event | outcome | n | rate | half1 | half2 |")
        md.append("| --- | --- | --- | --- | --- | --- |")
        for c in claims:
            md.append("| %s | %s | %d | %s | %s | %s |" % (
                c["event"], c["outcome"], c["n"],
                fmt_rate(c["wins"], c["n"], c["rate"]),
                fmt_rate(c["h1_w"], c["h1_n"], c["h1"]),
                fmt_rate(c["h2_w"], c["h2_n"], c["h2"]),
            ))
    md.append("")
    if membership_hot:
        md.append("Membership-only cells that numerically hit 90% (NOT buyable fills):")
        md.append("")
        md.append("| event | outcome | n | rate | half1 | half2 |")
        md.append("| --- | --- | --- | --- | --- | --- |")
        for c in membership_hot:
            md.append("| %s | %s | %d | %s | %s | %s |" % (
                c["event"], c["outcome"], c["n"],
                fmt_rate(c["wins"], c["n"], c["rate"]),
                fmt_rate(c["h1_w"], c["h1_n"], c["h1"]),
                fmt_rate(c["h2_w"], c["h2_n"], c["h2"]),
            ))
        md.append("")
    md.append("## 4. Best BUYABLE cells by outcome (n>=30, non-一字 t)")
    md.append("")
    for ok in [
        "open_then_zt3", "touch3", "open_follow", "open_follow_flat",
        "hold_close", "hold_not_lose", "hold_touch3", "cons_not_lose",
        "hold_3d", "open_3d", "maxclose3",
    ]:
        pool = best_for(ok, 30)
        md.append("### `%s`" % ok)
        md.append("")
        if not pool:
            md.append("No n>=30 cell (usually means daily bars not joined yet).")
            md.append("")
            continue
        md.append("| event | n | rate | half1 | half2 |")
        md.append("| --- | --- | --- | --- | --- |")
        for c in pool:
            md.append("| %s | %d | %s | %s | %s |" % (
                c["event"], c["n"],
                fmt_rate(c["wins"], c["n"], c["rate"]),
                fmt_rate(c["h1_w"], c["h1_n"], c["h1"]),
                fmt_rate(c["h2_w"], c["h2_n"], c["h2"]),
            ))
        md.append("")
    md.append("## 5. 3-day membership (not a fill) — new target")
    md.append("")
    md.append("Selected at t, non-一字, outcome = in zt_pool on t+1 or t+2 or t+3.")
    md.append("")
    md.append("| event | n | zt_3d | half1 | half2 |")
    md.append("| --- | --- | --- | --- | --- |")
    for ev_name, _pred in named:
        if ev_name in diagnostic:
            continue
        c = next(x for x in cells if x["event"] == ev_name and x["outcome"] == "zt_3d")
        if c["n"] < 15:
            continue
        md.append("| %s | %d | %s | %s | %s |" % (
            ev_name, c["n"],
            fmt_rate(c["wins"], c["n"], c["rate"]),
            fmt_rate(c["h1_w"], c["h1_n"], c["h1"]),
            fmt_rate(c["h2_w"], c["h2_n"], c["h2"]),
        ))
    md.append("")
    md.append("## 6. Theme persistence (theme-day, not a stock fill)")
    md.append("")
    md.append("Selection uses t theme counts only. Win = that theme still has enough 涨停 on t+1.")
    md.append("")
    md.append("| rule | n | rate | half1 | half2 |")
    md.append("| --- | --- | --- | --- | --- |")
    for tr in theme_rows:
        md.append("| %s | %d | %s | %s | %s |" % (
            tr["rule"], tr["n"],
            fmt_rate(tr["wins"], tr["n"], tr["rate"]),
            fmt_rate(tr["h1_w"], tr["h1_n"], tr["h1"]),
            fmt_rate(tr["h2_w"], tr["h2_n"], tr["h2"]),
        ))
    md.append("")
    md.append("## 7. What is missing to continue")
    md.append("")
    if cov["bar_codes"] < cov["bar_need"] or cov["fail_n1_bar"] < cov["fail_n"]:
        md.append("- Daily bars still incomplete: %d/%d codes, fail t+1 %d/%d. Re-run `python tools/relay_study/fetch_daily_bars.py` then this hunter." % (
            cov["bar_codes"], cov["bar_need"], cov["fail_n1_bar"], cov["fail_n"]
        ))
    else:
        md.append("- Daily bars for the 连板 universe are in. Remaining gaps: 竞价 matched amount / 开板价 / 分时 (auction file still empty).")
    md.append("- No 分时, no 竞价, no 炸板价 path inside the day. 回封打板 still cannot be filled from these files.")
    md.append("- `his_daban_list` exists on the kaipanla client but is outside the backfill contract; not fetched.")
    md.append("- To go further on 90% buyable: need either a much narrower t-known event than the ones below, or 竞价/开板 prints.")
    md.append("")
    md.append("Files: `out/buyable_cells.csv`, `out/missing_next_bars.csv`, `out/theme_persist.csv`, `out/daily_bars/`.")
    md.append("Re-run: `python tools/relay_study/hunt_buyable.py`")
    md.append("")

    text = "\n".join(md)
    (OUT / "buyable_hunt.md").write_text(text, encoding="utf-8")
    # also copy to the path the user asked: tools/relay_study/out/buyable_hunt.md is that path
    print("wrote", OUT / "buyable_hunt.md")
    print("claims", len(claims), "membership_hot", len(membership_hot))
    print("missing bars", len(missing), "bar codes", cov["bar_codes"])
    # print top buyable
    for ok in ["open_then_zt3", "touch3", "hold_close", "cons_not_lose", "zt_3d"]:
        pool = best_for(ok, 20)
        if pool:
            c = pool[0]
            print("BEST", ok, c["event"], fmt_rate(c["wins"], c["n"], c["rate"]), "h1", fmt_rate(c["h1_w"], c["h1_n"], c["h1"]), "h2", fmt_rate(c["h2_w"], c["h2_n"], c["h2"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
