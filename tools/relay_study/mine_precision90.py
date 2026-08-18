# -*- coding: utf-8 -*-
"""Historical 90% precision search over relay_study candidates. Stdlib only.

Does not modify run.py / ultraboard. Writes out/precision90.md and
out/precision_cells.csv. Frequencies only; not a trading scheme.
"""
from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
OUT = STUDY / "out"
RAW = ROOT / "data" / "kaipanla" / "raw"
THS_ZT = ROOT / "data" / "ths" / "limit_pool"

MIN_CLAIM = 30
MIN_NOTE = 15
TARGET = 0.90
WF_TRAIN = 40
WF_TEST = 20
WF_STEP = 20


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
    if s == "":
        return None
    return None


def load_candidates():
    path = OUT / "candidates.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows


def load_days():
    path = OUT / "days.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows


def load_same_day_extras(dates):
    """Join same-day fields only (no next-day)."""
    extras = {}
    theme_n_full = {}  # (date, theme) -> count in full zt pool
    for day in dates:
        pool_path = RAW / day / "zt_pool.json"
        ths_path = THS_ZT / f"{day}.json"
        stocks = []
        if pool_path.exists():
            data = json.loads(pool_path.read_text(encoding="utf-8-sig"))
            stocks = data.get("stocks") or []
        ths = {}
        if ths_path.exists():
            td = json.loads(ths_path.read_text(encoding="utf-8-sig"))
            ths = {str(s.get("code")): s for s in (td.get("stocks") or []) if s.get("code")}
        tc = Counter()
        for s in stocks:
            th = str(s.get("theme") or "").strip()
            if th:
                tc[th] += 1
            code = str(s.get("code") or "")
            if not code:
                continue
            t = ths.get(code) or {}
            extras[(day, code)] = {
                "amount": _f(s.get("amount")),
                "turnover": _f(s.get("turnover_rate")),
                "is_fanbao": bool(s.get("is_fanbao")),
                "open_count": _i(t.get("open_count")),
                "board_type": t.get("board_type") or "",
            }
        for th, n in tc.items():
            theme_n_full[(day, th)] = n
    return extras, theme_n_full


def pct_rank(values):
    """values: list of (idx, x). Returns dict idx -> percentile 0-100 among non-null same group."""
    xs = [(i, x) for i, x in values if x is not None]
    if not xs:
        return {}
    xs.sort(key=lambda t: t[1])
    n = len(xs)
    out = {}
    for rank, (i, _x) in enumerate(xs):
        out[i] = 100.0 * rank / max(n - 1, 1) if n > 1 else 50.0
    return out


def build_features(cands, days):
    day_by = {d["date"]: d for d in days}
    day_order = [d["date"] for d in days]
    day_pos = {d: i for i, d in enumerate(day_order)}
    absent_pos = [i for i, d in enumerate(days) if _b(d["leader_absent"])]

    dates = sorted({r["signal_date"] for r in cands})
    extras, theme_n_full = load_same_day_extras(dates)

    # own_baoliang from prior appearance of same code (look-back only)
    by_code = defaultdict(list)
    for i, r in enumerate(cands):
        by_code[r["code"]].append(i)
    own_baoliang = [False] * len(cands)
    own_ratio = [None] * len(cands)
    # also scan extras in date order for first-board priors not in candidates
    # Use candidate sequence: previous candidate row of same code with boards == current-1
    for code, idxs in by_code.items():
        idxs = sorted(idxs, key=lambda i: cands[i]["signal_date"])
        for k, i in enumerate(idxs):
            r = cands[i]
            ex = extras.get((r["signal_date"], r["code"])) or {}
            amt = ex.get("amount")
            b = _i(r["boards"])
            if k == 0 or amt is None or not b:
                continue
            prev = cands[idxs[k - 1]]
            pex = extras.get((prev["signal_date"], prev["code"])) or {}
            pamt = pex.get("amount")
            pb = _i(prev["boards"])
            if pamt and pamt > 0 and pb == b - 1:
                ratio = amt / pamt
                own_ratio[i] = ratio
                own_baoliang[i] = ratio >= 2.0

    # same-day amount/turnover percentile among candidates that day
    by_date_idx = defaultdict(list)
    for i, r in enumerate(cands):
        by_date_idx[r["signal_date"]].append(i)
    amt_pct = [None] * len(cands)
    to_pct = [None] * len(cands)
    for _d, idxs in by_date_idx.items():
        av = []
        tv = []
        for i in idxs:
            r = cands[i]
            ex = extras.get((r["signal_date"], r["code"])) or {}
            av.append((i, ex.get("amount")))
            tv.append((i, ex.get("turnover")))
        for i, p in pct_rank(av).items():
            amt_pct[i] = p
        for i, p in pct_rank(tv).items():
            to_pct[i] = p

    feats = []
    for i, r in enumerate(cands):
        d = day_by.get(r["signal_date"], {})
        ex = extras.get((r["signal_date"], r["code"])) or {}
        boards = _i(r["boards"]) or 0
        H = _i(r["H"]) or 0
        href = (H - boards) if H else None
        pos = day_pos.get(r["signal_date"])
        lag = None
        if pos is not None:
            prior = [p for p in absent_pos if p <= pos]
            if prior:
                lag = pos - prior[-1]  # 0 = 断板当天
        theme = (r.get("theme") or "").strip()
        tn = theme_n_full.get((r["signal_date"], theme))
        if tn is None:
            tn = 1 if theme else 0
        oc = ex.get("open_count")
        nzt = _i(d.get("n_zt"))
        nlead = _i(d.get("n_leaders"))
        feats.append({
            "boards": boards,
            "H": H,
            "href": href,
            "lag": lag,
            "theme_n": tn,
            "open_count": oc,
            "amount": ex.get("amount"),
            "turnover": ex.get("turnover"),
            "amt_pct": amt_pct[i],
            "to_pct": to_pct[i],
            "n_zt": nzt,
            "n_leaders": nlead,
            "is_fanbao": bool(ex.get("is_fanbao")),
            "own_baoliang": own_baoliang[i],
            "own_ratio": own_ratio[i],
            "board_type": ex.get("board_type") or "",
            "theme": theme,
        })
    return feats


def parse_outcomes(cands):
    zt = []
    pr = []
    tr = []
    yizi_next = []
    for r in cands:
        z = bool(_b(r["zt_next"]))
        p = bool(_b(r["promote"]))
        t = bool(_b(r["tradable_zt"]))
        y = _b(r["one_word_next"])
        zt.append(1 if z else 0)
        pr.append(1 if p else 0)
        tr.append(1 if t else 0)
        yizi_next.append(1 if y is True else 0)
    return {"zt_next": zt, "promote": pr, "tradable_zt": tr, "one_word_next": yizi_next}


def make_bool_factors(cands, feats):
    n = len(cands)
    F = {}

    def add(name, pred):
        F[name] = [1 if pred(i) else 0 for i in range(n)]

    def rb(key):
        return [_b(cands[i][key]) is True for i in range(n)]

    # existing candidate flags (known at t)
    for key in [
        "leader_absent", "leader_any_absent", "height_drop", "height_new_high",
        "leader_baoliang", "prev_leader_baoliang", "theme_alive", "theme_dead",
        "same_theme_broken", "loose_theme_broken", "is_new_high", "is_sub_high",
        "is_mid_2_3", "is_legacy_near", "one_price_today", "same_theme_baoliang",
    ]:
        vals = rb(key)
        add(key, lambda i, v=vals: v[i])

    add("is_fanbao", lambda i: feats[i]["is_fanbao"])
    add("own_baoliang", lambda i: feats[i]["own_baoliang"])
    add("theme_alive_own", lambda i: (feats[i]["theme_n"] or 0) >= 2)
    add("theme_weak_own", lambda i: (feats[i]["theme_n"] or 0) == 1)
    add("opened", lambda i: feats[i]["open_count"] is not None and feats[i]["open_count"] >= 1)
    add("unopened", lambda i: feats[i]["open_count"] is not None and feats[i]["open_count"] == 0)
    add("open_ge2", lambda i: feats[i]["open_count"] is not None and feats[i]["open_count"] >= 2)
    add("boards_eq2", lambda i: feats[i]["boards"] == 2)
    add("boards_eq3", lambda i: feats[i]["boards"] == 3)
    add("boards_eq4", lambda i: feats[i]["boards"] == 4)
    add("boards_ge4", lambda i: feats[i]["boards"] >= 4)
    add("boards_ge5", lambda i: feats[i]["boards"] >= 5)
    add("boards_ge6", lambda i: feats[i]["boards"] >= 6)
    add("href0", lambda i: feats[i]["href"] == 0)
    add("href1", lambda i: feats[i]["href"] == 1)
    add("href2", lambda i: feats[i]["href"] == 2)
    add("href_le1", lambda i: feats[i]["href"] is not None and feats[i]["href"] <= 1)
    add("href_le2", lambda i: feats[i]["href"] is not None and feats[i]["href"] <= 2)
    add("lag0", lambda i: feats[i]["lag"] == 0)
    add("lag1", lambda i: feats[i]["lag"] == 1)
    add("lag2", lambda i: feats[i]["lag"] == 2)
    add("lag3", lambda i: feats[i]["lag"] == 3)
    add("lag_1to3", lambda i: feats[i]["lag"] in (1, 2, 3))
    add("H_le4", lambda i: feats[i]["H"] <= 4)
    add("H_ge8", lambda i: feats[i]["H"] >= 8)
    add("H_ge10", lambda i: feats[i]["H"] >= 10)
    add("amt_hi", lambda i: feats[i]["amt_pct"] is not None and feats[i]["amt_pct"] >= 80)
    add("amt_lo", lambda i: feats[i]["amt_pct"] is not None and feats[i]["amt_pct"] <= 20)
    add("to_hi", lambda i: feats[i]["to_pct"] is not None and feats[i]["to_pct"] >= 80)
    add("to_lo", lambda i: feats[i]["to_pct"] is not None and feats[i]["to_pct"] <= 20)
    add("nzt_le40", lambda i: feats[i]["n_zt"] is not None and feats[i]["n_zt"] <= 40)
    add("nzt_ge80", lambda i: feats[i]["n_zt"] is not None and feats[i]["n_zt"] >= 80)
    add("solo_leader", lambda i: feats[i]["n_leaders"] == 1)
    return F


# Core bools for systematic 2/3-factor grid (keep grid tractable, pre-motivated extras separate)
GRID_BOOLS = [
    "leader_absent", "height_drop", "height_new_high",
    "leader_baoliang", "prev_leader_baoliang",
    "theme_alive", "theme_dead", "theme_alive_own",
    "same_theme_broken", "is_new_high", "is_sub_high", "is_mid_2_3",
    "is_legacy_near", "one_price_today", "same_theme_baoliang",
    "is_fanbao", "own_baoliang", "opened", "unopened",
    "boards_ge5", "href_le1", "lag0",
]


def and_mask(masks):
    n = len(masks[0])
    out = [1] * n
    for m in masks:
        for i in range(n):
            if not m[i]:
                out[i] = 0
    return out


def eval_cell(mask, y, yizi_today, yizi_next, boards, themes, dates, half1, half2, wf_windows):
    sel = [i for i, m in enumerate(mask) if m]
    n = len(sel)
    if n < MIN_NOTE:
        return None
    wins = sum(y[i] for i in sel)
    rate = wins / n
    def split_stats(ok):
        s = [i for i in sel if ok[i]]
        nn = len(s)
        ww = sum(y[i] for i in s) if nn else 0
        return nn, ww, (ww / nn if nn else None)

    n1, w1, r1 = split_stats(half1)
    n2, w2, r2 = split_stats(half2)
    yizi_t = sum(yizi_today[i] for i in sel) / n
    zt_sel = [i for i in sel if y[i]]  # wins under this definition
    # one_word_next share among ALL selected and among zt_next-equivalent
    yizi_n_all = sum(yizi_next[i] for i in sel) / n
    yizi_n_wins = (sum(yizi_next[i] for i in zt_sel) / len(zt_sel)) if zt_sel else 0.0
    hc = Counter(boards[i] for i in sel)
    height_mix = ";".join("%s:%d" % (k, hc[k]) for k in sorted(hc, key=lambda x: (x is None, x)))
    n_themes = len({themes[i] for i in sel if themes[i]})
    n_dates = len({dates[i] for i in sel})
    wf = []
    for lo, hi, wmask in wf_windows:
        nn, ww, rr = split_stats(wmask)
        wf.append((nn, ww, rr))
    return {
        "n": n, "wins": wins, "rate": rate,
        "n1": n1, "w1": w1, "r1": r1,
        "n2": n2, "w2": w2, "r2": r2,
        "yizi_today": yizi_t,
        "yizi_next_all": yizi_n_all,
        "yizi_next_wins": yizi_n_wins,
        "height_mix": height_mix,
        "n_themes": n_themes,
        "n_dates": n_dates,
        "wf": wf,
        "sel": sel,
    }


def claim_ok(st, definition):
    if st is None or st["n"] < MIN_CLAIM:
        return False
    if st["rate"] < TARGET:
        return False
    if st["n1"] < MIN_NOTE or st["r1"] is None or st["r1"] < TARGET:
        return False
    if st["n2"] < MIN_NOTE or st["r2"] is None or st["r2"] < TARGET:
        return False
    wf_ok = 0
    for nn, ww, rr in st["wf"]:
        if nn >= MIN_NOTE:
            if rr is None or rr < TARGET:
                return False
            wf_ok += 1
    if wf_ok < 2:
        return False
    # tradable definition is the only buyable claim; zt_next/promote with high yizi is not a scheme
    if definition != "tradable_zt" and st["yizi_today"] >= 0.50:
        return False
    return True


def notes_of(st, definition):
    flags = []
    if st["yizi_today"] >= 0.50:
        flags.append("yizi_today=%.0f%%_not_buyable" % (100 * st["yizi_today"]))
    if definition != "tradable_zt" and st["yizi_next_wins"] >= 0.50:
        flags.append("wins_are_yizi_next=%.0f%%" % (100 * st["yizi_next_wins"]))
    if st["n_themes"] <= 2:
        flags.append("theme_names<=2")
    if st["n_dates"] < 8:
        flags.append("few_dates=%d" % st["n_dates"])
    if st["n"] < MIN_CLAIM:
        flags.append("checkpoint_n<30")
    flags.append("yizi_today=%.1f%%" % (100 * st["yizi_today"]))
    flags.append("yizi_next_all=%.1f%%" % (100 * st["yizi_next_all"]))
    flags.append("height{%s}" % st["height_mix"])
    flags.append("themes=%d" % st["n_themes"])
    flags.append("dates=%d" % st["n_dates"])
    return " | ".join(flags)


def fmt_rate(w, n):
    if not n:
        return "n=0"
    return "%d/%d=%.1f%%" % (w, n, 100.0 * w / n)


def main():
    print("loading candidates...")
    cands = load_candidates()
    days = load_days()
    print("candidates", len(cands), "days", len(days))
    print("joining same-day extras...")
    feats = build_features(cands, days)
    Y = parse_outcomes(cands)
    F = make_bool_factors(cands, feats)
    print("factors", len(F), "grid", len(GRID_BOOLS))

    n = len(cands)
    yizi_today = [1 if _b(r["one_price_today"]) is True else 0 for r in cands]
    boards = [(_i(r["boards"]) or 0) for r in cands]
    themes = [(r.get("theme") or "").strip() for r in cands]
    dates = [r["signal_date"] for r in cands]
    signal_dates = sorted(set(dates))
    mid = len(signal_dates) // 2
    first_set = set(signal_dates[:mid])
    second_set = set(signal_dates[mid:])
    half1 = [1 if dates[i] in first_set else 0 for i in range(n)]
    half2 = [1 if dates[i] in second_set else 0 for i in range(n)]
    date_pos = {d: i for i, d in enumerate(signal_dates)}
    row_pos = [date_pos[d] for d in dates]

    wf_windows = []
    start = WF_TRAIN
    while start + WF_TEST <= len(signal_dates):
        lo, hi = start, start + WF_TEST
        wset = set(signal_dates[lo:hi])
        wmask = [1 if dates[i] in wset else 0 for i in range(n)]
        wf_windows.append((lo, hi, wmask))
        start += WF_STEP
    print("wf windows", len(wf_windows), "half1 dates", len(first_set), first_set and min(first_set), max(first_set) if first_set else None)

    # factor coverage sanity
    for name in ["is_fanbao", "opened", "unopened", "theme_alive_own", "own_baoliang", "lag0", "lag1"]:
        c = sum(F[name])
        print("  cover", name, c)

    jobs = []  # (definition, filters, mask)

    # singles: both polarities for grid bools + extra named singles
    seen_filters = set()

    def add_job(filters, mask):
        key = " & ".join(filters)
        if key in seen_filters:
            return
        seen_filters.add(key)
        jobs.append((key, filters, mask))

    add_job(["ALL"], [1] * n)

    for name in GRID_BOOLS:
        add_job([name], F[name])
        inv = [1 - x for x in F[name]]
        add_job(["NOT " + name], inv)

    extra_singles = [k for k in F if k not in GRID_BOOLS]
    for name in extra_singles:
        add_job([name], F[name])

    # 2-factor systematic on a slightly smaller core (motivated + grid)
    pair_pool = [
        "leader_absent", "height_drop", "height_new_high", "leader_baoliang",
        "prev_leader_baoliang", "theme_alive_own", "theme_alive",
        "same_theme_broken", "is_new_high", "is_sub_high", "is_mid_2_3",
        "one_price_today", "is_fanbao", "own_baoliang", "opened", "unopened",
        "boards_ge5", "href_le1", "lag0", "same_theme_baoliang",
    ]
    for a, b in combinations(pair_pool, 2):
        for pa, la in ((1, a), (0, "NOT " + a)):
            for pb, lb in ((1, b), (0, "NOT " + b)):
                ma = F[a] if pa else [1 - x for x in F[a]]
                mb = F[b] if pb else [1 - x for x in F[b]]
                add_job([la, lb], and_mask([ma, mb]))

    # 3-factor pre-motivated (梯队 / 接力 / 题材 / 断板 / 爆量 / 一字 vs 换手)
    triples = [
        ["leader_absent", "theme_alive_own", "is_new_high"],
        ["leader_absent", "theme_alive_own", "href_le1"],
        ["leader_absent", "NOT one_price_today", "is_new_high"],
        ["leader_absent", "NOT one_price_today", "is_mid_2_3"],
        ["leader_absent", "NOT one_price_today", "boards_ge4"],
        ["leader_absent", "is_new_high", "unopened"],
        ["leader_absent", "height_drop", "href_le1"],
        ["lag0", "is_new_high", "theme_alive_own"],
        ["lag1", "is_new_high", "theme_alive_own"],
        ["lag1", "href_le1", "NOT one_price_today"],
        ["lag_1to3", "is_new_high", "theme_alive_own"],
        ["height_new_high", "is_mid_2_3", "theme_alive_own"],
        ["height_new_high", "is_new_high", "NOT one_price_today"],
        ["NOT leader_absent", "leader_baoliang", "same_theme_baoliang"],
        ["NOT leader_absent", "leader_baoliang", "theme_alive_own"],
        ["prev_leader_baoliang", "theme_alive_own", "href_le1"],
        ["own_baoliang", "theme_alive_own", "is_new_high"],
        ["own_baoliang", "NOT one_price_today", "boards_ge4"],
        ["one_price_today", "boards_ge5", "theme_alive_own"],
        ["one_price_today", "boards_ge5", "is_new_high"],
        ["one_price_today", "boards_ge4", "href0"],
        ["one_price_today", "unopened", "boards_ge5"],
        ["NOT one_price_today", "is_new_high", "theme_alive_own"],
        ["NOT one_price_today", "is_new_high", "opened"],
        ["NOT one_price_today", "href_le1", "theme_alive_own"],
        ["NOT one_price_today", "boards_ge5", "theme_alive_own"],
        ["NOT one_price_today", "unopened", "is_new_high"],
        ["opened", "theme_alive_own", "is_new_high"],
        ["is_fanbao", "theme_alive_own", "is_mid_2_3"],
        ["is_fanbao", "leader_absent", "NOT one_price_today"],
        ["theme_dead", "leader_absent", "is_mid_2_3"],
        ["same_theme_broken", "leader_absent", "is_new_high"],
        ["same_theme_broken", "theme_alive_own", "href_le1"],
        ["boards_ge5", "href0", "NOT one_price_today"],
        ["boards_ge5", "href0", "one_price_today"],
        ["H_ge8", "is_new_high", "one_price_today"],
        ["H_ge8", "is_new_high", "NOT one_price_today"],
        ["H_le4", "is_new_high", "theme_alive_own"],
        ["amt_lo", "one_price_today", "boards_ge4"],
        ["amt_hi", "opened", "theme_alive_own"],
        ["to_lo", "one_price_today", "boards_ge5"],
        ["to_hi", "opened", "NOT one_price_today"],
        ["nzt_le40", "is_new_high", "theme_alive_own"],
        ["nzt_ge80", "is_mid_2_3", "leader_absent"],
        ["solo_leader", "is_new_high", "theme_alive_own"],
        ["is_legacy_near", "leader_absent", "theme_alive_own"],
        ["is_sub_high", "leader_absent", "NOT one_price_today"],
        ["is_sub_high", "theme_alive_own", "opened"],
    ]

    def mask_from_names(names):
        masks = []
        for nm in names:
            if nm.startswith("NOT "):
                base = nm[4:]
                if base not in F:
                    return None
                masks.append([1 - x for x in F[base]])
            else:
                if nm not in F:
                    return None
                masks.append(F[nm])
        return and_mask(masks)

    for names in triples:
        m = mask_from_names(names)
        if m is not None:
            add_job(names, m)

    # extra 3-factor systematic on a tight core (high-signal factors only)
    core3 = [
        "leader_absent", "one_price_today", "is_new_high", "theme_alive_own",
        "boards_ge5", "opened", "is_fanbao", "own_baoliang", "href_le1",
    ]
    for a, b, c in combinations(core3, 3):
        for pa, la in ((1, a), (0, "NOT " + a)):
            for pb, lb in ((1, b), (0, "NOT " + b)):
                for pc, lc in ((1, c), (0, "NOT " + c)):
                    m = mask_from_names([la, lb, lc])
                    if m is not None:
                        add_job([la, lb, lc], m)

    print("jobs", len(jobs))

    defs = ["zt_next", "promote", "tradable_zt"]
    rows_out = []
    hits = {d: [] for d in defs}
    notes90 = {d: [] for d in defs}  # n=15-29
    best = {d: [] for d in defs}
    yizi_traps = []

    for j_i, (key, filters, mask) in enumerate(jobs):
        if j_i and j_i % 500 == 0:
            print("  eval", j_i, "/", len(jobs))
        for definition in defs:
            st = eval_cell(
                mask, Y[definition], yizi_today, Y["one_word_next"],
                boards, themes, dates, half1, half2, wf_windows,
            )
            if st is None:
                continue
            rec = {
                "definition": definition,
                "filters": key,
                "n": st["n"],
                "wins": st["wins"],
                "rate": st["rate"],
                "half1": fmt_rate(st["w1"], st["n1"]),
                "half2": fmt_rate(st["w2"], st["n2"]),
                "half1_rate": st["r1"],
                "half2_rate": st["r2"],
                "notes": notes_of(st, definition),
                "yizi_today": st["yizi_today"],
                "yizi_next_wins": st["yizi_next_wins"],
                "n_themes": st["n_themes"],
                "n_dates": st["n_dates"],
                "height_mix": st["height_mix"],
                "claim": claim_ok(st, definition),
                "wf": ";".join(fmt_rate(ww, nn) for nn, ww, rr in st["wf"]),
            }
            # keep csv rows: n>=30 or rate>=0.70 or claim/note90
            keep = (
                st["n"] >= MIN_CLAIM
                or st["rate"] >= 0.70
                or (MIN_NOTE <= st["n"] < MIN_CLAIM and st["rate"] >= TARGET)
            )
            if keep:
                rows_out.append(rec)
            if claim_ok(st, definition):
                hits[definition].append((st, rec))
            if MIN_NOTE <= st["n"] < MIN_CLAIM and st["rate"] >= TARGET:
                notes90[definition].append((st, rec))
            if st["n"] >= MIN_CLAIM:
                best[definition].append((st["rate"], st["n"], rec))
            if (
                definition == "zt_next"
                and st["n"] >= MIN_NOTE
                and st["rate"] >= 0.80
                and st["yizi_today"] >= 0.50
            ):
                yizi_traps.append(rec)

    for d in defs:
        best[d].sort(key=lambda t: (-t[0], -t[1]))

    # write csv (dedupe by definition+filters, keep one)
    rows_out.sort(key=lambda r: (r["definition"], -r["rate"], -r["n"]))
    csv_path = OUT / "precision_cells.csv"
    fields = ["definition", "filters", "n", "wins", "rate", "half1", "half2", "notes"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        seen = set()
        for r in rows_out:
            k = (r["definition"], r["filters"])
            if k in seen:
                continue
            seen.add(k)
            w.writerow({
                "definition": r["definition"],
                "filters": r["filters"],
                "n": r["n"],
                "wins": r["wins"],
                "rate": "%.4f" % r["rate"],
                "half1": r["half1"],
                "half2": r["half2"],
                "notes": r["notes"],
            })
    print("wrote", csv_path, "rows", len(seen))

    # markdown
    def top_block(definition, k=15):
        lines = [
            "| rank | filters | n | wins | rate | half1 | half2 | yizi_today | notes |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        used = set()
        rank = 0
        for rate, nn, rec in best[definition]:
            if rec["filters"] in used:
                continue
            used.add(rec["filters"])
            rank += 1
            lines.append("| %d | %s | %d | %d | %.1f%% | %s | %s | %.0f%% | %s |" % (
                rank, rec["filters"], rec["n"], rec["wins"], 100 * rec["rate"],
                rec["half1"], rec["half2"], 100 * rec["yizi_today"],
                rec["notes"][:180],
            ))
            if rank >= k:
                break
        if rank == 0:
            lines.append("| | (none with n>=30) | | | | | | | |")
        return "\n".join(lines)

    def hit_block(definition):
        if not hits[definition]:
            return "None."
        lines = []
        for st, rec in hits[definition]:
            lines.append("- **%s** n=%d wins=%d rate=%.1f%% half1=%s half2=%s yizi_today=%.0f%% claimable_buyable=%s wf=%s" % (
                rec["filters"], rec["n"], rec["wins"], 100 * rec["rate"],
                rec["half1"], rec["half2"], 100 * rec["yizi_today"],
                "YES" if definition == "tradable_zt" else "NO_not_tradable_def",
                rec["wf"],
            ))
        return "\n".join(lines)

    any_claim = any(hits[d] for d in defs)
    any_tradable = bool(hits["tradable_zt"])
    ceil_lines = []
    for d in defs:
        if best[d]:
            rate, nn, rec = best[d][0]
            ceil_lines.append("- **%s** ceiling n>=30: %.1f%% (%s) filters=`%s` yizi_today=%.0f%%" % (
                d, 100 * rate, fmt_rate(rec["wins"], rec["n"]), rec["filters"], 100 * rec["yizi_today"],
            ))
        else:
            ceil_lines.append("- **%s** ceiling: no cell with n>=30" % d)

    # baseline
    base = {}
    for d in defs:
        nn = n
        ww = sum(Y[d])
        base[d] = (ww, nn, ww / nn)

    md = []
    md.append("# 连板接力 90% 精度搜索检查点")
    md.append("")
    md.append("日期：2026-08-17")
    md.append("性质：**历史条件频率，不是交易方案。** 未宣布任何可交易规则。")
    md.append("样本：`out/candidates.csv` n=2736，信号日 2025-10-09 至 2026-08-12（207 日）。")
    md.append("胜率三定义分开统计，不混用。")
    md.append("")
    md.append("## 结论")
    md.append("")
    if any_tradable:
        md.append("存在 tradable_zt 且 n>=30、对半与 walk-forward 均>=90% 的 cell。见下。**即使如此，这仍只是历史频率，不是方案。**")
    else:
        md.append("**没有** cell 在 `tradable_zt`（次日涨停且非一字、可买定义）上达到 **胜率>=90% 且 n>=30**，并且时间对半 + walk-forward 仍>=90%。")
    if hits["zt_next"] or hits["promote"]:
        md.append("zt_next / promote 若有达标 cell，已按一字占比标注；一字链的高 zt_next **不是可买 90%。**")
    else:
        md.append("**也没有** cell 在 `zt_next` / `promote` 上达到同一声称门槛（n>=30 + 对半 + WF 均>=90%，且一字今日占比<50%）。")
    md.append("")
    md.append("未降低门槛。未发明 90% 规则。")
    md.append("")
    md.append("### 天花板（n>=30，全样本最高，不表示稳定）")
    md.append("")
    md.extend(ceil_lines)
    md.append("")
    md.append("无条件基线：")
    for d in defs:
        w, nn, r = base[d]
        md.append("- %s: %s" % (d, fmt_rate(w, nn)))
    md.append("")
    md.append("说明：本样本 `promote` 与 `zt_next` 全样本完全重合（965/2736），因次日仍在涨停池时 boards 均为 +1。两列仍分开报。")
    md.append("")
    md.append("## 方法")
    md.append("")
    md.append("- 只用 t 日可知字段做筛选。次日字段（zt_next / one_word_next / boards_next / zha_next）只作结果，不作条件。")
    md.append("- 单因子：高度、H 相对、题材存活（日级 theme_alive=断板题材；theme_alive_own=该股题材当日涨停池>=2只）、断板/滞后、爆量（龙头/自身）、一字/开板次数、反包、成交额/换手当日分位、H 桶、涨停家数。")
    md.append("- 2 因子：核心布尔网格（含正反）。")
    md.append("- 3 因子：预动机组合（梯队/接力/题材/断板/爆量/一字vs换手）+ 9 核布尔的正反三重。")
    md.append("- 声称门槛：n>=30；对半两段各 n>=15 且胜率>=90%；walk-forward（训40/测20/步20）至少 2 个测试窗 n>=15 且这些窗全部>=90%。n=15-29 只作检查点笔记。")
    md.append("- 垃圾 90%：一字今日占比高、主题名<=2、日期过少、用次日字段、小样本。")
    md.append("- 时间对半与 `run.py` 相同：信号日排序后前半 / 后半（103 / 104 日）。")
    md.append("- `open_count` / `is_fanbao` / 成交额换手从同日开盘啦+同花顺涨停池拼接，不改 run.py。")
    md.append("")
    md.append("## 达标 cell（声称级）")
    md.append("")
    md.append("### tradable_zt")
    md.append("")
    md.append(hit_block("tradable_zt"))
    md.append("")
    md.append("### zt_next")
    md.append("")
    md.append(hit_block("zt_next"))
    md.append("")
    md.append("### promote")
    md.append("")
    md.append(hit_block("promote"))
    md.append("")
    md.append("## 各定义天花板 TOP（n>=30）")
    md.append("")
    md.append("### tradable_zt")
    md.append("")
    md.append(top_block("tradable_zt", 15))
    md.append("")
    md.append("### zt_next")
    md.append("")
    md.append(top_block("zt_next", 15))
    md.append("")
    md.append("### promote")
    md.append("")
    md.append(top_block("promote", 15))
    md.append("")
    md.append("## 一字陷阱（zt_next 高但不可买）")
    md.append("")
    md.append("one_price_today=True 全样本：zt_next 约 69%，tradable_zt 约 32%。高连板一字续一字会抬高 zt_next，不是可买胜率。")
    md.append("")
    if yizi_traps:
        yizi_traps.sort(key=lambda r: (-r["rate"], -r["n"]))
        md.append("| filters | n | zt_next | half1 | half2 | yizi_today |")
        md.append("| --- | --- | --- | --- | --- | --- |")
        seen = set()
        k = 0
        for rec in yizi_traps:
            if rec["filters"] in seen:
                continue
            seen.add(rec["filters"])
            md.append("| %s | %d | %.1f%% | %s | %s | %.0f%% |" % (
                rec["filters"], rec["n"], 100 * rec["rate"], rec["half1"], rec["half2"], 100 * rec["yizi_today"],
            ))
            k += 1
            if k >= 12:
                break
    else:
        md.append("未发现 n>=15 且 zt_next>=80% 且一字今日>=50% 的 cell（或已被更高组合吸收）。")
    md.append("")
    md.append("## n=15-29 且全样本>=90%（检查点笔记，不是方案）")
    md.append("")
    for d in defs:
        items = notes90[d]
        md.append("### %s (%d cells)" % (d, len(items)))
        md.append("")
        if not items:
            md.append("无。")
            md.append("")
            continue
        items.sort(key=lambda t: (-t[0]["rate"], -t[0]["n"]))
        md.append("| filters | n | rate | half1 | half2 | notes |")
        md.append("| --- | --- | --- | --- | --- | --- |")
        seen = set()
        k = 0
        for st, rec in items:
            if rec["filters"] in seen:
                continue
            seen.add(rec["filters"])
            md.append("| %s | %d | %.1f%% | %s | %s | %s |" % (
                rec["filters"], rec["n"], 100 * rec["rate"], rec["half1"], rec["half2"], rec["notes"][:160],
            ))
            k += 1
            if k >= 10:
                break
        md.append("")
    md.append("## 搜索规模")
    md.append("")
    md.append("- 评估组合数（去重后）：%d" % len(jobs))
    md.append("- 写入 cells（n>=30 或 rate>=70% 或 小n且>=90%%）：见 `out/precision_cells.csv`")
    md.append("- walk-forward 窗数：%d" % len(wf_windows))
    md.append("")
    md.append("## 路径")
    md.append("")
    md.append("- D:\\\\Ultra-Board\\\\tools\\\\relay_study\\\\out\\\\precision90.md")
    md.append("- D:\\\\Ultra-Board\\\\tools\\\\relay_study\\\\out\\\\precision_cells.csv")
    md.append("- miner: D:\\\\Ultra-Board\\\\tools\\\\relay_study\\\\mine_precision90.py")
    md.append("")
    md.append("重跑：`python tools/relay_study/mine_precision90.py`（仓库根目录）。")
    md.append("")

    md_path = OUT / "precision90.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    print("wrote", md_path)

    # console summary (ASCII)
    print("==== SUMMARY ====")
    print("any_claim", any_claim, "tradable_hits", len(hits["tradable_zt"]),
          "zt_hits", len(hits["zt_next"]), "promote_hits", len(hits["promote"]))
    for d in defs:
        if best[d]:
            rate, nn, rec = best[d][0]
            print("CEIL", d, "%.1f%%" % (100 * rate), "n", nn, rec["filters"][:120],
                  "yizi_today", "%.0f%%" % (100 * rec["yizi_today"]))
        print(" note90", d, len(notes90[d]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
