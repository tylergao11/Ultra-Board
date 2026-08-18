# -*- coding: utf-8 -*-
"""Buyable-path hunt 2: verify 38/46, name-pick inside persistent themes, squeeze.

Stdlib + existing local caches only. Does not modify ultraboard/ or data contracts.
Writes tools/relay_study/out/buyable_hunt2.md and name_pick_cells.csv.
"""
from __future__ import annotations

import csv
import datetime
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
OUT = STUDY / "out"
RAW = ROOT / "data" / "kaipanla" / "raw"
THS = ROOT / "data" / "ths" / "limit_pool"
BAR = OUT / "daily_bars"
MIN_N = 30
MIN_HALF = 15
TARGET = 0.90
WINDOW_START = "2025-10-09"
WINDOW_END = "2026-08-12"
CN = datetime.timezone(datetime.timedelta(hours=8))


def _f(v):
    if v in (None, ""):
        return None
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _i(v):
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except Exception:
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


def limit_pct(code):
    return 20.0 if str(code).startswith(("300", "301", "688")) else 10.0


def limit_up(px, pct):
    if px is None or px <= 0:
        return None
    return round(px * (1 + pct / 100.0), 2)


def near(a, b, tol=0.011):
    return a is not None and b is not None and abs(a - b) <= tol


def fmt(w, n, rt):
    if n <= 0 or rt is None:
        return "n=0"
    return "%d/%d = %.1f%%" % (w, n, 100.0 * rt)


def pack(sel, key):
    used = [bool(r[key]) for r in sel if r.get(key) is not None]
    n = len(used)
    w = sum(used)
    return w, n, (w / n if n else None)


def load_all():
    rows = list(csv.DictReader((OUT / "candidates.csv").open(encoding="utf-8-sig")))
    days = list(csv.DictReader((OUT / "days.csv").open(encoding="utf-8-sig")))
    day_order = [d["date"] for d in days]
    pos = {d: i for i, d in enumerate(day_order)}
    bars = {}
    for p in BAR.glob("*.json"):
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
        bars[str(doc.get("code") or p.stem)] = doc.get("bars") or {}
    return rows, days, day_order, pos, bars


def load_day_extras(dates):
    ths_cache = {}
    kpl_cache = {}
    theme_n = Counter()
    theme_members = defaultdict(list)
    for day in dates:
        tp = THS / (day + ".json")
        if tp.exists():
            d = json.loads(tp.read_text(encoding="utf-8-sig"))
            ths_cache[day] = {str(s["code"]): s for s in (d.get("stocks") or []) if s.get("code")}
        else:
            ths_cache[day] = {}
        kp = RAW / day / "zt_pool.json"
        stocks = []
        if kp.exists():
            stocks = json.loads(kp.read_text(encoding="utf-8-sig")).get("stocks") or []
        kpl_cache[day] = {str(s.get("code")): s for s in stocks if s.get("code")}
        for s in stocks:
            th = str(s.get("theme") or "").strip()
            code = str(s.get("code") or "")
            if th and code:
                theme_n[(day, th)] += 1
                theme_members[(day, th)].append(code)
    return ths_cache, kpl_cache, theme_n, theme_members


def enrich(cands, day_order, pos, bars, ths_cache, kpl_cache, theme_n):
    out = []
    for r in cands:
        t = r["signal_date"]
        if t < WINDOW_START or t > WINDOW_END:
            continue
        u1 = r["outcome_date"]
        i = pos.get(t)
        u2 = day_order[i + 2] if i is not None and i + 2 < len(day_order) else None
        u3 = day_order[i + 3] if i is not None and i + 3 < len(day_order) else None
        th = (ths_cache.get(t) or {}).get(r["code"]) or {}
        kpl = (kpl_cache.get(t) or {}).get(r["code"]) or {}
        bmap = bars.get(r["code"]) or {}
        bar_t = bmap.get(t)
        bar1 = bmap.get(u1)
        bar2 = bmap.get(u2) if u2 else None
        bar3 = bmap.get(u3) if u3 else None
        # grid_buyable used THS price first (the 38/46 cell)
        px_ths = _f(th.get("price"))
        px_kpl = _f(kpl.get("price"))
        px_bar = _f(bar_t.get("c")) if bar_t else None
        px_t = px_ths if px_ths is not None else (px_bar if px_bar is not None else px_kpl)
        open1 = _f(bar1.get("o")) if bar1 else None
        high1 = _f(bar1.get("h")) if bar1 else None
        low1 = _f(bar1.get("l")) if bar1 else None
        close1 = _f(bar1.get("c")) if bar1 else None
        close2 = _f(bar2.get("c")) if bar2 else None
        close3 = _f(bar3.get("c")) if bar3 else None
        high2 = _f(bar2.get("h")) if bar2 else None
        high3 = _f(bar3.get("h")) if bar3 else None
        lp = limit_pct(r["code"])
        lim1 = limit_up(px_t, lp)
        yizi_open = False
        if open1 is not None and lim1 is not None:
            yizi_open = near(open1, lim1) and (high1 is None or near(high1, lim1)) and (low1 is None or near(low1, lim1))
        if _b(r.get("one_word_next")) is True and open1 is not None and close1 is not None and near(open1, close1):
            yizi_open = True
        buyable_open = open1 is not None and close1 is not None and not yizi_open
        ts = th.get("first_limit_ts") or kpl.get("first_limit_ts")
        final_ts = th.get("final_limit_ts")
        early = False
        first_tod = None
        if ts:
            dt = datetime.datetime.fromtimestamp(int(ts), CN)
            early = dt.hour < 10
            first_tod = dt.hour * 60 + dt.minute
        seal = _f(th.get("seal_order_ratio"))
        suc = _f(th.get("limit_up_success_rate"))
        oc = _i(th.get("open_count"))
        amt = _f(kpl.get("amount"))
        turn = _f(kpl.get("turnover_rate"))
        if turn is None:
            turn = _f(th.get("turnover_rate"))
        circ = _f(th.get("circulating_market_cap"))
        theme = (r.get("theme") or "").strip()
        tn = theme_n.get((t, theme), 0)
        boards = _i(r["boards"]) or 0
        H = _i(r.get("H")) or 0
        win_days = _i(th.get("limit_up_window_days"))
        stock_broken = None
        if win_days is not None and boards:
            stock_broken = win_days > boards
        one_t = _b(r["one_price_today"])
        zt3 = bool(_b(r["zt_next"]) or _b(r.get("zt_d2")) or _b(r.get("zt_d3")))
        hold_close = (close1 > px_t) if (px_t is not None and close1 is not None) else None
        hold_flat = (close1 >= px_t * 0.999) if (px_t is not None and close1 is not None) else None
        open_up = (close1 > open1) if buyable_open else None
        open_flat = (close1 >= open1 * 0.999) if buyable_open else None

        def _touch(bars_seq, start_px):
            if start_px is None:
                return None
            hits = []
            prev = start_px
            any_bar = False
            for bar in bars_seq:
                if not bar or prev is None:
                    hits.append(False)
                    continue
                any_bar = True
                lim = limit_up(prev, lp)
                h = _f(bar.get("h"))
                c = _f(bar.get("c"))
                hits.append(bool(lim and h is not None and h >= lim - 0.011))
                if c is not None:
                    prev = c
            if not any_bar:
                return None
            return any(hits)

        touch3 = _touch((bar1, bar2, bar3), px_t) if buyable_open else None
        hold_touch3 = _touch((bar1, bar2, bar3), px_t) if one_t is False else None
        hold_3d = (close3 > px_t) if (px_t is not None and close3 is not None) else None
        open_3d = (close3 > open1) if buyable_open and close3 is not None else None
        cs = [c for c in (close1, close2, close3) if c is not None]
        maxc3 = (max(cs) > px_t) if (px_t is not None and cs) else None
        rec = {
            "date": t, "u1": u1, "u2": u2, "u3": u3,
            "code": r["code"], "name": r.get("name") or "",
            "theme": theme, "boards": boards, "H": H,
            "one_t": one_t,
            "px_t": px_t, "px_ths": px_ths, "px_kpl": px_kpl, "px_bar": px_bar,
            "open1": open1, "close1": close1, "close2": close2, "close3": close3,
            "high1": high1, "high2": high2, "high3": high3,
            "yizi_open": yizi_open, "buyable_open": buyable_open,
            "seal": seal, "suc": suc, "oc": oc if oc is not None else -1,
            "amt": amt, "turn": turn, "circ": circ,
            "tn": tn, "early": early, "first_tod": first_tod,
            "first_ts": _i(ts), "final_ts": _i(final_ts),
            "fanbao": bool(kpl.get("is_fanbao")),
            "board_type": th.get("board_type") or "",
            "stock_broken": stock_broken,
            "absent": bool(_b(r["leader_absent"])),
            "drop": bool(_b(r["height_drop"])),
            "newh": bool(_b(r["is_new_high"])),
            "sub": bool(_b(r["is_sub_high"])),
            "mid": bool(_b(r["is_mid_2_3"])),
            "same": bool(_b(r["same_theme_broken"])),
            "alive": bool(_b(r["theme_alive"])),
            "zt_next": bool(_b(r["zt_next"])),
            "zha_next": bool(_b(r["zha_next"])),
            "hold_close": hold_close, "hold_flat": hold_flat,
            "open_up": open_up, "open_flat": open_flat,
            "touch3": touch3, "hold_touch3": hold_touch3,
            "hold_3d": hold_3d, "open_3d": open_3d, "maxc3": maxc3,
            "zt3": zt3, "open_zt3": zt3 if buyable_open else None,
            "hold_zt3": zt3 if one_t is False else None,
        }
        out.append(rec)
    return out


def halves(rows):
    dates = sorted({r["date"] for r in rows})
    mid = len(dates) // 2
    return set(dates[:mid]), set(dates[mid:]), dates


def cell(sel, key, first, second):
    w, n, rt = pack(sel, key)
    w1, n1, r1 = pack([r for r in sel if r["date"] in first], key)
    w2, n2, r2 = pack([r for r in sel if r["date"] in second], key)
    claim = (
        n >= MIN_N and rt is not None and rt >= TARGET
        and n1 >= MIN_HALF and r1 is not None and r1 >= TARGET
        and n2 >= MIN_HALF and r2 is not None and r2 >= TARGET
    )
    return {
        "wins": w, "n": n, "rate": rt,
        "h1_w": w1, "h1_n": n1, "h1": r1,
        "h2_w": w2, "h2_n": n2, "h2": r2,
        "claim": claim,
    }


def ny(rows):
    return [r for r in rows if r["one_t"] is False]


def verify_3846(rows, first, second):
    """Rebuild grid cell: boards>=4 & seal>=2% & theme_n>=5, non-yizi, maxc3."""
    base = [r for r in ny(rows) if r["boards"] >= 4 and r["seal"] is not None and r["seal"] >= 0.02 and r["tn"] >= 5]
    used = [r for r in base if r.get("maxc3") is not None]
    notes = []
    notes.append("rebuild n_base=%d n_with_maxc3=%d" % (len(base), len(used)))
    c = cell(used, "maxc3", first, second)
    notes.append("maxc3 %s h1 %s h2 %s claim=%s" % (
        fmt(c["wins"], c["n"], c["rate"]),
        fmt(c["h1_w"], c["h1_n"], c["h1"]),
        fmt(c["h2_w"], c["h2_n"], c["h2"]),
        c["claim"],
    ))
    # price source disagreement
    disagree = [r for r in used if r["px_ths"] is not None and r["px_bar"] is not None and abs(r["px_ths"] - r["px_bar"]) > 0.02]
    notes.append("ths_vs_bar_close disagree n=%d / %d" % (len(disagree), len(used)))
    # spot-check first 8 and last 6 against raw bars
    spots = used[:8] + used[-6:]
    spot_ok = 0
    spot_lines = []
    for r in spots:
        bmap = None
        # recompute from stored closes
        cs = [c for c in (r["close1"], r["close2"], r["close3"]) if c is not None]
        recomputed = max(cs) > r["px_t"] if cs and r["px_t"] is not None else None
        match = recomputed == r["maxc3"]
        if match:
            spot_ok += 1
        spot_lines.append({
            "date": r["date"], "code": r["code"], "name": r["name"],
            "boards": r["boards"], "tn": r["tn"], "seal": r["seal"],
            "px_t": r["px_t"], "px_ths": r["px_ths"], "px_bar": r["px_bar"],
            "c1": r["close1"], "c2": r["close2"], "c3": r["close3"],
            "maxc3": r["maxc3"], "recomputed": recomputed, "match": match,
        })
    notes.append("spot-check stored vs recomputed %d/%d" % (spot_ok, len(spots)))
    return used, c, notes, spot_lines, disagree


def pick_one(cands, keyfn, reverse=False):
    """Deterministic: sort by keyfn then code."""
    if not cands:
        return None
    def k(r):
        val = keyfn(r)
        return (val is None, val, r["code"])
    ordered = sorted(cands, key=k, reverse=reverse)
    # reverse=True would invert None-last incorrectly; handle manually
    present = [r for r in cands if keyfn(r) is not None]
    missing = [r for r in cands if keyfn(r) is None]
    if not present:
        return None
    if reverse:
        present = sorted(present, key=lambda r: (keyfn(r), r["code"]), reverse=True)
    else:
        present = sorted(present, key=lambda r: (keyfn(r), r["code"]))
    return present[0]


SELECTORS = [
    ("earliest_seal", lambda pool: pick_one(pool, lambda r: r["first_ts"], False)),
    ("latest_seal", lambda pool: pick_one(pool, lambda r: r["first_ts"], True)),
    ("strongest_seal", lambda pool: pick_one(pool, lambda r: r["seal"], True)),
    ("weakest_seal", lambda pool: pick_one(pool, lambda r: r["seal"], False)),
    ("fewest_opens", lambda pool: pick_one([r for r in pool if r["oc"] >= 0], lambda r: (r["oc"], -(r["seal"] or -1)), False)),
    ("unopened_strongest", lambda pool: pick_one([r for r in pool if r["oc"] == 0], lambda r: r["seal"], True)),
    ("unopened_earliest", lambda pool: pick_one([r for r in pool if r["oc"] == 0], lambda r: r["first_ts"], False)),
    ("opened_strongest", lambda pool: pick_one([r for r in pool if r["oc"] >= 1], lambda r: r["seal"], True)),
    ("fanbao_strongest", lambda pool: pick_one([r for r in pool if r["fanbao"]], lambda r: r["seal"], True)),
    ("earliest_final", lambda pool: pick_one(pool, lambda r: r["final_ts"], False)),
    ("highest_board", lambda pool: pick_one(pool, lambda r: (r["boards"], r["seal"] if r["seal"] is not None else -1), True)),
    ("lowest_board", lambda pool: pick_one(pool, lambda r: (r["boards"], -(r["seal"] or -1)), False)),
    ("board2_strongest", lambda pool: pick_one([r for r in pool if r["boards"] == 2], lambda r: r["seal"], True)),
    ("board3_strongest", lambda pool: pick_one([r for r in pool if r["boards"] == 3], lambda r: r["seal"], True)),
    ("board4_strongest", lambda pool: pick_one([r for r in pool if r["boards"] == 4], lambda r: r["seal"], True)),
    ("board5p_strongest", lambda pool: pick_one([r for r in pool if r["boards"] >= 5], lambda r: r["seal"], True)),
    ("board2_earliest", lambda pool: pick_one([r for r in pool if r["boards"] == 2], lambda r: r["first_ts"], False)),
    ("board3_earliest", lambda pool: pick_one([r for r in pool if r["boards"] == 3], lambda r: r["first_ts"], False)),
    ("cihigh_strongest", lambda pool: pick_one([r for r in pool if r["sub"]], lambda r: r["seal"], True)),
    ("mid_strongest", lambda pool: pick_one([r for r in pool if r["mid"]], lambda r: r["seal"], True)),
    ("newh_strongest", lambda pool: pick_one([r for r in pool if r["newh"]], lambda r: r["seal"], True)),
    ("mid_earliest", lambda pool: pick_one([r for r in pool if r["mid"]], lambda r: r["first_ts"], False)),
    ("cihigh_earliest", lambda pool: pick_one([r for r in pool if r["sub"]], lambda r: r["first_ts"], False)),
    ("max_amount", lambda pool: pick_one(pool, lambda r: r["amt"], True)),
    ("min_amount", lambda pool: pick_one(pool, lambda r: r["amt"], False)),
    ("max_turn", lambda pool: pick_one(pool, lambda r: r["turn"], True)),
    ("min_turn", lambda pool: pick_one(pool, lambda r: r["turn"], False)),
    ("intact_strongest", lambda pool: pick_one([r for r in pool if (not r["absent"]) and (not r["drop"])], lambda r: r["seal"], True)),
    ("intact_earliest", lambda pool: pick_one([r for r in pool if (not r["absent"]) and (not r["drop"])], lambda r: r["first_ts"], False)),
    ("break_strongest", lambda pool: pick_one([r for r in pool if r["drop"] or r["same"]], lambda r: r["seal"], True)),
    ("stock_unbroken_strongest", lambda pool: pick_one([r for r in pool if r["stock_broken"] is False], lambda r: r["seal"], True)),
    ("stock_broken_strongest", lambda pool: pick_one([r for r in pool if r["stock_broken"] is True], lambda r: r["seal"], True)),
    ("stock_unbroken_earliest", lambda pool: pick_one([r for r in pool if r["stock_broken"] is False], lambda r: r["first_ts"], False)),
    ("H_strongest", lambda pool: pick_one([r for r in pool if r["H"] and r["boards"] == r["H"]], lambda r: r["seal"], True)),
    ("Hm1_strongest", lambda pool: pick_one([r for r in pool if r["H"] and r["boards"] == r["H"] - 1], lambda r: r["seal"], True)),
    ("belowH_strongest", lambda pool: pick_one([r for r in pool if r["H"] and r["boards"] < r["H"]], lambda r: r["seal"], True)),
    ("ge3_strongest", lambda pool: pick_one([r for r in pool if r["boards"] >= 3], lambda r: r["seal"], True)),
    ("ge3_earliest", lambda pool: pick_one([r for r in pool if r["boards"] >= 3], lambda r: r["first_ts"], False)),
    ("ge4_strongest", lambda pool: pick_one([r for r in pool if r["boards"] >= 4], lambda r: r["seal"], True)),
    ("ge4_earliest", lambda pool: pick_one([r for r in pool if r["boards"] >= 4], lambda r: r["first_ts"], False)),
    ("ge4_unopened", lambda pool: pick_one([r for r in pool if r["boards"] >= 4 and r["oc"] == 0], lambda r: r["seal"], True)),
    ("ge3_unopened", lambda pool: pick_one([r for r in pool if r["boards"] >= 3 and r["oc"] == 0], lambda r: r["seal"], True)),
    ("suc_strongest", lambda pool: pick_one(pool, lambda r: r["suc"], True)),
    ("early_strongest", lambda pool: pick_one([r for r in pool if r["early"]], lambda r: r["seal"], True)),
    ("huanshou_strongest", lambda pool: pick_one([r for r in pool if r["board_type"] == "换手板"], lambda r: r["seal"], True)),
    ("tzi_strongest", lambda pool: pick_one([r for r in pool if r["board_type"] == "T字板"], lambda r: r["seal"], True)),
]


def name_pick(rows, first, second, theme_n_min, mode):
    """mode: 'per_day' or 'per_theme_day'."""
    ny_rows = ny(rows)
    by_day = defaultdict(list)
    for r in ny_rows:
        if r["tn"] >= theme_n_min:
            by_day[r["date"]].append(r)
    results = []
    for sel_name, sel_fn in SELECTORS:
        picks = []
        if mode == "per_day":
            for day, pool in sorted(by_day.items()):
                # if multiple themes, keep names whose own theme meets threshold (already filtered)
                one = sel_fn(pool)
                if one is not None:
                    picks.append(one)
        else:
            # per (day, theme)
            groups = defaultdict(list)
            for r in ny_rows:
                if r["tn"] >= theme_n_min:
                    groups[(r["date"], r["theme"])].append(r)
            for key, pool in sorted(groups.items()):
                one = sel_fn(pool)
                if one is not None:
                    picks.append(one)
        for outcome in ("hold_close", "hold_flat", "hold_touch3", "maxc3", "open_up", "open_flat", "touch3", "open_zt3", "hold_zt3"):
            c = cell(picks, outcome, first, second)
            results.append({
                "mode": mode,
                "theme_n_min": theme_n_min,
                "selector": sel_name,
                "outcome": outcome,
                **c,
            })
    return results


def squeeze(rows, first, second):
    """Add one t-known factor at a time around the 82.6% cell."""
    base_pred = lambda r: (
        r["one_t"] is False
        and r["boards"] >= 4
        and r["seal"] is not None and r["seal"] >= 0.02
        and r["tn"] >= 5
    )
    extras = [
        ("base", lambda r: True),
        ("intact", lambda r: (not r["absent"]) and (not r["drop"])),
        ("absent", lambda r: r["absent"]),
        ("drop", lambda r: r["drop"]),
        ("not_drop", lambda r: not r["drop"]),
        ("same_break", lambda r: r["same"]),
        ("not_same", lambda r: not r["same"]),
        ("seal03", lambda r: r["seal"] is not None and r["seal"] >= 0.03),
        ("seal05", lambda r: r["seal"] is not None and r["seal"] >= 0.05),
        ("seal08", lambda r: r["seal"] is not None and r["seal"] >= 0.08),
        ("tn6", lambda r: r["tn"] >= 6),
        ("tn8", lambda r: r["tn"] >= 8),
        ("tn10", lambda r: r["tn"] >= 10),
        ("unopened", lambda r: r["oc"] == 0),
        ("opened", lambda r: r["oc"] >= 1),
        ("early", lambda r: r["early"]),
        ("not_early", lambda r: not r["early"]),
        ("suc8", lambda r: r["suc"] is not None and r["suc"] >= 0.8),
        ("newh", lambda r: r["newh"]),
        ("sub", lambda r: r["sub"]),
        ("mid", lambda r: r["mid"]),
        ("fanbao", lambda r: r["fanbao"]),
        ("not_fanbao", lambda r: not r["fanbao"]),
        ("stock_unbroken", lambda r: r["stock_broken"] is False),
        ("stock_broken", lambda r: r["stock_broken"] is True),
        ("eqH", lambda r: r["H"] and r["boards"] == r["H"]),
        ("eqHm1", lambda r: r["H"] and r["boards"] == r["H"] - 1),
        ("belowH", lambda r: r["H"] and r["boards"] < r["H"]),
        ("ge5", lambda r: r["boards"] >= 5),
        ("eq4", lambda r: r["boards"] == 4),
        ("amt_mid", lambda r: r["amt"] is not None and 5e7 <= r["amt"] <= 4e8),
        ("turn_mid", lambda r: r["turn"] is not None and 5 <= r["turn"] <= 25),
        ("circ_mid", lambda r: r["circ"] is not None and 3e9 <= r["circ"] <= 2e10),
        ("huanshou", lambda r: r["board_type"] == "换手板"),
        ("intact_unopened", lambda r: (not r["absent"]) and (not r["drop"]) and r["oc"] == 0),
        ("intact_tn8", lambda r: (not r["absent"]) and (not r["drop"]) and r["tn"] >= 8),
        ("unopened_tn8", lambda r: r["oc"] == 0 and r["tn"] >= 8),
        ("unopened_seal03", lambda r: r["oc"] == 0 and r["seal"] is not None and r["seal"] >= 0.03),
        ("intact_seal03", lambda r: (not r["absent"]) and (not r["drop"]) and r["seal"] is not None and r["seal"] >= 0.03),
        ("stock_unbroken_unopened", lambda r: r["stock_broken"] is False and r["oc"] == 0),
        ("stock_unbroken_tn8", lambda r: r["stock_broken"] is False and r["tn"] >= 8),
        ("early_unopened", lambda r: r["early"] and r["oc"] == 0),
        ("ge4_tn8_unopened", lambda r: r["tn"] >= 8 and r["oc"] == 0),
    ]
    # alternate bases
    bases = [
        ("ge4_seal02_tn5", base_pred),
        ("ge3_seal02_tn8", lambda r: r["one_t"] is False and r["boards"] >= 3 and r["seal"] is not None and r["seal"] >= 0.02 and r["tn"] >= 8),
        ("ge4_seal02_tn8", lambda r: r["one_t"] is False and r["boards"] >= 4 and r["seal"] is not None and r["seal"] >= 0.02 and r["tn"] >= 8),
        ("ge4_seal03_tn5", lambda r: r["one_t"] is False and r["boards"] >= 4 and r["seal"] is not None and r["seal"] >= 0.03 and r["tn"] >= 5),
        ("ge5_seal02_tn5", lambda r: r["one_t"] is False and r["boards"] >= 5 and r["seal"] is not None and r["seal"] >= 0.02 and r["tn"] >= 5),
        ("ge3_seal05_tn5", lambda r: r["one_t"] is False and r["boards"] >= 3 and r["seal"] is not None and r["seal"] >= 0.05 and r["tn"] >= 5),
        ("ge4_unopened_tn5", lambda r: r["one_t"] is False and r["boards"] >= 4 and r["oc"] == 0 and r["tn"] >= 5),
        ("ge4_unbroken_tn5", lambda r: r["one_t"] is False and r["boards"] >= 4 and r["stock_broken"] is False and r["tn"] >= 5),
        ("ge4_intact_tn5", lambda r: r["one_t"] is False and r["boards"] >= 4 and (not r["absent"]) and (not r["drop"]) and r["tn"] >= 5),
        ("ge3_unopened_tn8", lambda r: r["one_t"] is False and r["boards"] >= 3 and r["oc"] == 0 and r["tn"] >= 8),
        ("ge4_seal02_tn6", lambda r: r["one_t"] is False and r["boards"] >= 4 and r["seal"] is not None and r["seal"] >= 0.02 and r["tn"] >= 6),
        ("ge2_seal02_tn8", lambda r: r["one_t"] is False and r["boards"] >= 2 and r["seal"] is not None and r["seal"] >= 0.02 and r["tn"] >= 8),
    ]
    outcomes = ["maxc3", "hold_close", "hold_flat", "hold_touch3", "open_up", "open_flat", "touch3", "hold_3d"]
    hits = []
    # neighborhood around base
    for extra_name, extra in extras:
        sel = [r for r in rows if base_pred(r) and extra(r)]
        for ok in outcomes:
            c = cell(sel, ok, first, second)
            hits.append({"family": "squeeze_base", "filters": "ge4_seal02_tn5+" + extra_name, "outcome": ok, **c})
    for bname, bpred in bases:
        sel = [r for r in rows if bpred(r)]
        for ok in outcomes:
            c = cell(sel, ok, first, second)
            hits.append({"family": "alt_base", "filters": bname, "outcome": ok, **c})
        # one extra on a few promising alt bases
        if bname in ("ge4_seal02_tn8", "ge3_seal02_tn8", "ge4_unopened_tn5", "ge4_unbroken_tn5", "ge3_unopened_tn8"):
            for extra_name, extra in extras:
                if extra_name == "base":
                    continue
                sel2 = [r for r in sel if extra(r)]
                for ok in outcomes:
                    c = cell(sel2, ok, first, second)
                    hits.append({"family": "alt_plus", "filters": bname + "+" + extra_name, "outcome": ok, **c})
    return hits


def name_pick_max_theme(rows, first, second, theme_n_min):
    """Per day: restrict to the single largest theme (name tie-break), then pick 1."""
    ny_rows = ny(rows)
    by_day = defaultdict(list)
    for r in ny_rows:
        if r["tn"] >= theme_n_min:
            by_day[r["date"]].append(r)
    results = []
    for sel_name, sel_fn in SELECTORS:
        picks = []
        for day, pool in sorted(by_day.items()):
            # largest theme
            tn_by = Counter(r["theme"] for r in pool)
            # use row.tn as authority
            best_th = None
            best_n = -1
            for r in pool:
                if r["tn"] > best_n or (r["tn"] == best_n and (best_th is None or r["theme"] < best_th)):
                    best_n = r["tn"]
                    best_th = r["theme"]
            sub = [r for r in pool if r["theme"] == best_th]
            one = sel_fn(sub)
            if one is not None:
                picks.append(one)
        for outcome in ("hold_close", "hold_flat", "hold_touch3", "maxc3", "open_up", "open_flat", "touch3", "open_zt3", "hold_zt3"):
            c = cell(picks, outcome, first, second)
            results.append({
                "mode": "per_day_max_theme",
                "theme_n_min": theme_n_min,
                "selector": sel_name,
                "outcome": outcome,
                **c,
            })
    return results


def raw_bar_spotcheck(used, bars, n=10):
    """Re-read daily_bars JSON for several cell members."""
    lines = []
    ok = 0
    sample = used[:: max(1, len(used) // n)][:n]
    if used and used[0] not in sample:
        sample = [used[0]] + sample
    if used and used[-1] not in sample:
        sample = sample + [used[-1]]
    for r in sample:
        bmap = bars.get(r["code"]) or {}
        bt = bmap.get(r["date"])
        b1 = bmap.get(r["u1"])
        b2 = bmap.get(r["u2"]) if r["u2"] else None
        b3 = bmap.get(r["u3"]) if r["u3"] else None
        raw_c_t = _f(bt.get("c")) if bt else None
        raw_cs = []
        for b in (b1, b2, b3):
            if b and _f(b.get("c")) is not None:
                raw_cs.append(_f(b.get("c")))
        raw_max = max(raw_cs) if raw_cs else None
        raw_win = (raw_max > r["px_t"]) if (raw_max is not None and r["px_t"] is not None) else None
        match = raw_win == r["maxc3"]
        if match:
            ok += 1
        lines.append({
            "date": r["date"], "code": r["code"], "name": r["name"],
            "px_t": r["px_t"], "raw_c_t": raw_c_t,
            "raw_c1": _f(b1.get("c")) if b1 else None,
            "raw_c2": _f(b2.get("c")) if b2 else None,
            "raw_c3": _f(b3.get("c")) if b3 else None,
            "stored_maxc3": r["maxc3"], "raw_win": raw_win, "match": match,
            "has_t_bar": bt is not None, "has_n1": b1 is not None,
        })
    return ok, len(sample), lines


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            rec = dict(r)
            for k in ("rate", "h1", "h2"):
                if rec.get(k) is not None:
                    rec[k] = "%.4f" % rec[k]
            w.writerow(rec)


def md_cell(c):
    return "%s | h1 %s | h2 %s%s" % (
        fmt(c["wins"], c["n"], c["rate"]),
        fmt(c["h1_w"], c["h1_n"], c["h1"]),
        fmt(c["h2_w"], c["h2_n"], c["h2"]),
        " CLAIM" if c.get("claim") else "",
    )


def top_rows(rows, n=12, min_n=15):
    pool = [r for r in rows if (r.get("n") or 0) >= min_n and r.get("rate") is not None]
    pool.sort(key=lambda x: (-x["rate"], -x["n"]))
    return pool[:n]


def main():
    cands, days, day_order, pos, bars = load_all()
    dates = sorted({r["signal_date"] for r in cands if WINDOW_START <= r["signal_date"] <= WINDOW_END})
    ths_cache, kpl_cache, theme_n, theme_members = load_day_extras(dates)
    rows = enrich(cands, day_order, pos, bars, ths_cache, kpl_cache, theme_n)
    first, second, all_dates = halves(rows)
    mid_date = sorted(all_dates)[len(all_dates) // 2]
    print("enriched", len(rows), "ny", len(ny(rows)), "dates", len(all_dates), "mid", mid_date)

    used, c3846, vnotes, spot_lines, disagree = verify_3846(rows, first, second)
    raw_ok, raw_n, raw_lines = raw_bar_spotcheck(used, bars, n=12)
    print("VERIFY", vnotes)
    print("RAW_SPOT", raw_ok, "/", raw_n)
    for ln in raw_lines:
        print("  SPOT", ln)

    # name picks
    pick_rows = []
    for tnmin in (5, 6, 8, 10, 12):
        pick_rows.extend(name_pick(rows, first, second, tnmin, "per_day"))
        pick_rows.extend(name_pick(rows, first, second, tnmin, "per_theme_day"))
        pick_rows.extend(name_pick_max_theme(rows, first, second, tnmin))
    print("name_pick cells", len(pick_rows))
    claims_pick = [r for r in pick_rows if r.get("claim")]
    print("name_pick CLAIMS", len(claims_pick))
    for r in claims_pick[:30]:
        print("CLAIM", r["mode"], "tn>=%s" % r["theme_n_min"], r["selector"], r["outcome"], md_cell(r))

    squeeze_rows = squeeze(rows, first, second)
    print("squeeze cells", len(squeeze_rows))
    claims_sq = [r for r in squeeze_rows if r.get("claim")]
    print("squeeze CLAIMS", len(claims_sq))
    for r in claims_sq[:30]:
        print("CLAIM", r["filters"], r["outcome"], md_cell(r))

    # write csv
    fields = ["mode", "theme_n_min", "selector", "outcome", "n", "wins", "rate", "h1_n", "h1_w", "h1", "h2_n", "h2_w", "h2", "claim"]
    write_csv(OUT / "name_pick_cells.csv", pick_rows, fields)
    # breadcrumbs for thin squeeze
    sq_fields = ["family", "filters", "outcome", "n", "wins", "rate", "h1_n", "h1_w", "h1", "h2_n", "h2_w", "h2", "claim"]
    write_csv(OUT / "squeeze_cells.csv", squeeze_rows, sq_fields)

    # markdown
    lines = []
    lines.append("# Buyable-path hunt 2")
    lines.append("")
    lines.append("Date: 2026-08-17. Historical frequencies only. Not a trading scheme.")
    lines.append("Win-rate bar remains 90% on BUYABLE fills. 一字 continuation is discarded, not optimized.")
    lines.append("Halves: first %s.. mid-1 / second mid..%s. mid_date=%s." % (WINDOW_START, WINDOW_END, mid_date))
    lines.append("")
    lines.append("## 1. Verify 38/46 cell against raw daily_bars")
    lines.append("")
    lines.append("Definition (same as grid_buyable): non-一字 t, boards>=4, seal_order_ratio>=2%, own theme_n>=5.")
    lines.append("Buy = t close (THS limit_pool price, else bar close). Win = max(t+1..t+3 close) > buy.")
    lines.append("")
    for n in vnotes:
        lines.append("- " + n)
    lines.append("- raw daily_bars re-read spot-check: %d/%d match stored maxc3" % (raw_ok, raw_n))
    lines.append("")
    lines.append("Spot-check rows (raw bars):")
    lines.append("")
    lines.append("| date | code | name | px_t | raw_c_t | c1 | c2 | c3 | stored | raw_win | match |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for ln in raw_lines:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            ln["date"], ln["code"], ln["name"], ln["px_t"], ln["raw_c_t"],
            ln["raw_c1"], ln["raw_c2"], ln["raw_c3"], ln["stored_maxc3"], ln["raw_win"], ln["match"],
        ))
    if disagree:
        lines.append("")
        lines.append("THS price vs t bar close disagree (>0.02): %d (using THS as buy, matching prior grid)." % len(disagree))
        for r in disagree[:8]:
            lines.append("- %s %s %s ths=%s bar=%s" % (r["date"], r["code"], r["name"], r["px_ths"], r["px_bar"]))
    lines.append("")
    lines.append("Full cell members n=%d:" % len(used))
    lines.append("")
    lines.append("| date | code | name | boards | tn | seal | px_t | c1 | c2 | c3 | maxc3 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in used:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["date"], r["code"], r["name"], r["boards"], r["tn"],
            ("%.4f" % r["seal"]) if r["seal"] is not None else "",
            r["px_t"], r["close1"], r["close2"], r["close3"], r["maxc3"],
        ))
    lines.append("")

    lines.append("## 2. Name pick inside high-persistence theme days")
    lines.append("")
    lines.append("Universe: non-一字 t names whose own theme has theme_n >= threshold (t-known).")
    lines.append("Selectors are deterministic (key, then code). Days/themes with no eligible name are skipped, not backfilled.")
    lines.append("Modes: per_day (1 name/day), per_theme_day (1 name per theme-day), per_day_max_theme (largest theme that day, then 1 name).")
    lines.append("Outcomes from prices: hold_close / hold_flat (t close), open_up / open_flat (non-lock t+1 open), hold_touch3 / touch3, maxc3, *_zt3 membership.")
    lines.append("")
    claims_pick_sorted = sorted(claims_pick, key=lambda x: (-x["rate"], -x["n"]))
    if claims_pick_sorted:
        lines.append("**CLAIMED 90% name-pick cells:**")
        lines.append("")
        for r in claims_pick_sorted:
            lines.append("- %s tn>=%s %s %s → %s" % (r["mode"], r["theme_n_min"], r["selector"], r["outcome"], md_cell(r)))
        lines.append("")
    else:
        lines.append("**No name-pick cell hit 90% with n>=30 and both halves >=90%.**")
        lines.append("")
    lines.append("Best name-pick cells by outcome (n>=30):")
    lines.append("")
    for outcome in ("maxc3", "hold_close", "hold_flat", "hold_touch3", "open_up", "open_flat", "touch3"):
        pool = [r for r in pick_rows if r["outcome"] == outcome and r["n"] >= 30]
        pool.sort(key=lambda x: (-(x["rate"] or 0), -x["n"]))
        lines.append("### %s" % outcome)
        lines.append("")
        lines.append("| mode | tn | selector | n | rate | half1 | half2 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for r in pool[:8]:
            lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                r["mode"], r["theme_n_min"], r["selector"], r["n"],
                fmt(r["wins"], r["n"], r["rate"]),
                fmt(r["h1_w"], r["h1_n"], r["h1"]),
                fmt(r["h2_w"], r["h2_n"], r["h2"]),
            ))
        lines.append("")
    # thin breadcrumbs n=15-29 >=85%
    thin = [r for r in pick_rows if 15 <= r["n"] < 30 and r.get("rate") and r["rate"] >= 0.85]
    thin.sort(key=lambda x: (-x["rate"], -x["n"]))
    lines.append("Breadcrumbs (15<=n<30 and rate>=85%, not a scheme):")
    lines.append("")
    if not thin:
        lines.append("- none")
    for r in thin[:15]:
        lines.append("- %s tn>=%s %s %s → %s" % (r["mode"], r["theme_n_min"], r["selector"], r["outcome"], md_cell(r)))
    lines.append("")

    lines.append("## 3. Squeeze the 82.6% neighborhood")
    lines.append("")
    lines.append("Start from boards>=4 & seal>=2% & theme_n>=5, add one t-known factor. Also alternate bases.")
    lines.append("n<30 kept as breadcrumbs only.")
    lines.append("")
    if claims_sq:
        lines.append("**CLAIMED 90% squeeze cells:**")
        for r in claims_sq:
            lines.append("- %s %s → %s" % (r["filters"], r["outcome"], md_cell(r)))
        lines.append("")
    else:
        lines.append("**No squeeze cell hit 90% with n>=30 and both halves >=90%.**")
        lines.append("")
    lines.append("Best squeeze / alt-base cells n>=30:")
    lines.append("")
    lines.append("| family | filters | outcome | n | rate | half1 | half2 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    pool = [r for r in squeeze_rows if r["n"] >= 30]
    pool.sort(key=lambda x: (-(x["rate"] or 0), -x["n"]))
    seen = set()
    shown = 0
    for r in pool:
        key = (r["filters"], r["outcome"])
        if key in seen:
            continue
        seen.add(key)
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            r["family"], r["filters"], r["outcome"], r["n"],
            fmt(r["wins"], r["n"], r["rate"]),
            fmt(r["h1_w"], r["h1_n"], r["h1"]),
            fmt(r["h2_w"], r["h2_n"], r["h2"]),
        ))
        shown += 1
        if shown >= 25:
            break
    lines.append("")
    thin_sq = [r for r in squeeze_rows if 15 <= r["n"] < 30 and r.get("rate") and r["rate"] >= 0.85]
    thin_sq.sort(key=lambda x: (-x["rate"], -x["n"]))
    lines.append("Breadcrumbs (15<=n<30 rate>=85%):")
    lines.append("")
    if not thin_sq:
        lines.append("- none")
    for r in thin_sq[:20]:
        lines.append("- %s %s → %s" % (r["filters"], r["outcome"], md_cell(r)))
    lines.append("")

    lines.append("## 4. Auction / 打板 / 分时 probe (notes only until run)")
    lines.append("")
    lines.append("Filled after the bounded probe in the same session. See section 4b if present.")
    lines.append("")
    lines.append("- THS auction/tick: no dedicated endpoint in repo. `STOCK_LINE` `/v6/line/hs_{code}/01/` is daily OHLC only (already cached).")
    lines.append("- `data/research/auction/observations.jsonl` still empty; contract forbids fabricating 竞价 from close.")
    lines.append("- `KaipanlaClient.his_daban_list` is NOT in the backfill contract (backfill = sentiment/expression/zt_pool/sector_ladder only). Tiny 1-2 day schema probe only; no mass backfill.")
    lines.append("")
    lines.append("## 5. Files")
    lines.append("")
    lines.append("- `out/name_pick_cells.csv`")
    lines.append("- `out/squeeze_cells.csv` (breadcrumbs + full squeeze grid; prior buyable_* files untouched)")
    lines.append("- script: `tools/relay_study/hunt_buyable2.py`")
    lines.append("")

    (OUT / "buyable_hunt2.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote buyable_hunt2.md", len(lines), "lines")
    print("wrote name_pick_cells.csv", len(pick_rows))
    print("wrote squeeze_cells.csv", len(squeeze_rows))
    # print best overall buyable
    allc = pick_rows + squeeze_rows
    best = [r for r in allc if r.get("n", 0) >= 30 and r.get("rate")]
    best.sort(key=lambda x: (-x["rate"], -x["n"]))
    print("=== BEST n>=30 ===")
    for r in best[:15]:
        label = r.get("filters") or ("%s tn>=%s %s" % (r.get("mode"), r.get("theme_n_min"), r.get("selector")))
        print(label, r["outcome"], md_cell(r))


if __name__ == "__main__":
    main()

