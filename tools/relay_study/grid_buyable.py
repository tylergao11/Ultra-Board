# -*- coding: utf-8 -*-
"""Deeper named+combo scan on price outcomes. Stdlib. Does not claim a scheme."""
from __future__ import annotations

import csv
import datetime
import json
import math
from collections import defaultdict
from pathlib import Path

STUDY = Path(__file__).resolve().parent
OUT = STUDY / "out"
ROOT = STUDY.parents[1]
RAW = ROOT / "data" / "kaipanla" / "raw"
THS = ROOT / "data" / "ths" / "limit_pool"
BAR = OUT / "daily_bars"
MIN_N = 30
MIN_HALF = 15
TARGET = 0.90

def _f(v):
    if v in (None, ""): return None
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None

def _i(v):
    try: return int(float(v))
    except Exception: return None

def _b(v):
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"): return True
    if s in ("false", "0", "no"): return False
    return None

def limit_pct(code):
    return 20.0 if str(code).startswith(("300", "301", "688")) else 10.0

def limit_up(px, pct):
    if px is None or px <= 0: return None
    return round(px * (1 + pct / 100.0), 2)

def near(a, b, tol=0.011):
    return a is not None and b is not None and abs(a - b) <= tol

rows = list(csv.DictReader((OUT / "candidates.csv").open(encoding="utf-8-sig")))
days = list(csv.DictReader((OUT / "days.csv").open(encoding="utf-8-sig")))
day_order = [d["date"] for d in days]
pos = {d: i for i, d in enumerate(day_order)}

bars = {}
for p in BAR.glob("*.json"):
    doc = json.loads(p.read_text(encoding="utf-8-sig"))
    bars[p.stem] = doc.get("bars") or {}

ths_cache = {}
def ths_day(day):
    if day in ths_cache: return ths_cache[day]
    p = THS / (day + ".json")
    if not p.exists():
        ths_cache[day] = {}
        return {}
    d = json.loads(p.read_text(encoding="utf-8-sig"))
    ths_cache[day] = {str(s["code"]): s for s in d.get("stocks") or []}
    return ths_cache[day]

theme_full = defaultdict(int)
kpl_amt = {}
for day in sorted({r["signal_date"] for r in rows}):
    d = json.loads((RAW / day / "zt_pool.json").read_text(encoding="utf-8-sig"))
    for s in d.get("stocks") or []:
        th = str(s.get("theme") or "").strip()
        if th: theme_full[(day, th)] += 1
        kpl_amt[(day, str(s.get("code")))] = _f(s.get("amount"))

CN = datetime.timezone(datetime.timedelta(hours=8))
enriched = []
for r in rows:
    if _b(r["one_price_today"]) is not False:
        continue
    t = r["signal_date"]
    u1 = r["outcome_date"]
    i = pos.get(t)
    u2 = day_order[i + 2] if i is not None and i + 2 < len(day_order) else None
    u3 = day_order[i + 3] if i is not None and i + 3 < len(day_order) else None
    bmap = bars.get(r["code"]) or {}
    th = ths_day(t).get(r["code"]) or {}
    px_t = _f(th.get("price"))
    bar_t = bmap.get(t)
    if px_t is None and bar_t:
        px_t = _f(bar_t.get("c"))
    bar1, bar2, bar3 = bmap.get(u1), bmap.get(u2) if u2 else None, bmap.get(u3) if u3 else None
    open1 = _f(bar1.get("o")) if bar1 else None
    high1 = _f(bar1.get("h")) if bar1 else None
    close1 = _f(bar1.get("c")) if bar1 else None
    low1 = _f(bar1.get("l")) if bar1 else None
    close2 = _f(bar2.get("c")) if bar2 else None
    close3 = _f(bar3.get("c")) if bar3 else None
    lp = limit_pct(r["code"])
    lim1 = limit_up(px_t, lp)
    yizi_open = False
    if open1 is not None and lim1 is not None:
        yizi_open = near(open1, lim1) and (high1 is None or near(high1, lim1)) and (low1 is None or near(low1, lim1))
    if _b(r.get("one_word_next")) is True and open1 is not None and close1 is not None and near(open1, close1):
        yizi_open = True
    buyable_open = open1 is not None and close1 is not None and not yizi_open
    ts = th.get("first_limit_ts")
    early = False
    if ts:
        early = datetime.datetime.fromtimestamp(int(ts), CN).hour < 10
    seal = _f(th.get("seal_order_ratio"))
    suc = _f(th.get("limit_up_success_rate"))
    amt = kpl_amt.get((t, r["code"]))
    tn = theme_full[(t, (r.get("theme") or "").strip())]
    boards = _i(r["boards"]) or 0
    zt3 = bool(_b(r["zt_next"]) or _b(r.get("zt_d2")) or _b(r.get("zt_d3")))
    hold_close = (close1 > px_t) if (px_t is not None and close1 is not None) else None
    hold_flat = (close1 >= px_t * 0.999) if (px_t is not None and close1 is not None) else None
    open_up = (close1 > open1) if buyable_open else None
    open_flat = (close1 >= open1 * 0.999) if buyable_open else None
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
    hold_touch3 = None
    if px_t is not None and (bar1 or bar2 or bar3):
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
    hold_3d = (close3 > px_t) if (px_t is not None and close3 is not None) else None
    maxc3 = None
    cs = [c for c in (close1, close2, close3) if c is not None]
    if px_t is not None and cs:
        maxc3 = max(cs) > px_t
    rec = {
        "date": t,
        "boards": boards,
        "early": early,
        "strong": seal is not None and seal >= 0.02,
        "strong05": seal is not None and seal >= 0.05,
        "suc8": suc is not None and suc >= 0.8,
        "tn": tn,
        "amt": amt,
        "opened": (_i(th.get("open_count")) or 0) >= 1,
        "absent": bool(_b(r["leader_absent"])),
        "drop": bool(_b(r["height_drop"])),
        "newh": bool(_b(r["is_new_high"])),
        "sub": bool(_b(r["is_sub_high"])),
        "mid": bool(_b(r["is_mid_2_3"])),
        "same": bool(_b(r["same_theme_broken"])),
        "alive": bool(_b(r["theme_alive"])),
        "hold_close": hold_close,
        "hold_flat": hold_flat,
        "open_up": open_up,
        "open_flat": open_flat,
        "touch3": touch3,
        "hold_touch3": hold_touch3,
        "hold_3d": hold_3d,
        "maxc3": maxc3,
        "zt3": zt3,
        "open_zt3": zt3 if buyable_open else None,
    }
    enriched.append(rec)

dates = sorted({r["date"] for r in enriched})
mid = len(dates) // 2
first, second = set(dates[:mid]), set(dates[mid:])

flags = {
    "ge3": lambda r: r["boards"] >= 3,
    "ge4": lambda r: r["boards"] >= 4,
    "ge5": lambda r: r["boards"] >= 5,
    "eq3": lambda r: r["boards"] == 3,
    "eq2": lambda r: r["boards"] == 2,
    "early": lambda r: r["early"],
    "strong": lambda r: r["strong"],
    "strong05": lambda r: r["strong05"],
    "suc8": lambda r: r["suc8"],
    "tn5": lambda r: r["tn"] >= 5,
    "tn8": lambda r: r["tn"] >= 8,
    "opened": lambda r: r["opened"],
    "unopened": lambda r: not r["opened"],
    "absent": lambda r: r["absent"],
    "intact": lambda r: not r["absent"],
    "drop": lambda r: r["drop"],
    "newh": lambda r: r["newh"],
    "mid": lambda r: r["mid"],
    "amt_mid": lambda r: r["amt"] is not None and 5e7 <= r["amt"] <= 4e8,
}

# singles + pairs + a few triples from a core set
core = ["ge3", "ge4", "ge5", "eq3", "early", "strong", "tn5", "tn8", "intact", "absent", "newh", "mid", "opened", "suc8"]
combos = [()]
combos += [(a,) for a in flags]
combos += [(a, b) for i, a in enumerate(core) for b in core[i + 1:]]
# selected triples
triples = [
    ("ge3", "early", "strong"),
    ("ge4", "early", "strong"),
    ("ge3", "strong", "tn5"),
    ("ge4", "strong", "tn5"),
    ("eq3", "early", "tn5"),
    ("ge5", "early", "intact"),
    ("ge3", "intact", "strong"),
    ("mid", "tn8", "intact"),
    ("ge4", "intact", "tn5"),
    ("ge5", "strong", "tn5"),
]
combos += triples

outcomes = ["touch3", "hold_touch3", "hold_close", "hold_flat", "open_up", "open_flat", "hold_3d", "maxc3", "open_zt3", "zt3"]

def apply(r, keys):
    return all(flags[k](r) for k in keys)

def pack(sel, key):
    used = [bool(r[key]) for r in sel if r.get(key) is not None]
    n = len(used)
    w = sum(used)
    return w, n, (w / n if n else None)

hits = []
best = {ok: None for ok in outcomes}
for combo in combos:
    name = "&".join(combo) if combo else "ALL_ny"
    pred = (lambda r, combo=combo: apply(r, combo))
    sel = [r for r in enriched if pred(r)]
    if len(sel) < 15:
        continue
    for ok in outcomes:
        w, n, rt = pack(sel, ok)
        if n < 15 or rt is None:
            continue
        w1, n1, r1 = pack([r for r in sel if r["date"] in first], ok)
        w2, n2, r2 = pack([r for r in sel if r["date"] in second], ok)
        rec = {
            "filters": name, "outcome": ok, "n": n, "wins": w, "rate": rt,
            "h1_n": n1, "h1_w": w1, "h1": r1, "h2_n": n2, "h2_w": w2, "h2": r2,
            "claim": n >= MIN_N and rt >= TARGET and n1 >= MIN_HALF and (r1 or 0) >= TARGET and n2 >= MIN_HALF and (r2 or 0) >= TARGET,
        }
        hits.append(rec)
        cur = best[ok]
        if cur is None or (rt, n) > (cur["rate"], cur["n"]):
            if n >= 20:
                best[ok] = rec

claims = [h for h in hits if h["claim"]]
print("evaluated", len(hits), "claim90", len(claims))
for ok in outcomes:
    b = best[ok]
    if not b:
        print("BEST", ok, "none")
        continue
    print("BEST %s %s %d/%d=%.1f%% h1 %s h2 %s claim=%s" % (
        ok, b["filters"], b["wins"], b["n"], 100 * b["rate"],
        ("%.1f%% n=%d" % (100 * b["h1"], b["h1_n"])) if b["h1"] is not None else "na",
        ("%.1f%% n=%d" % (100 * b["h2"], b["h2_n"])) if b["h2"] is not None else "na",
        b["claim"],
    ))

# top 15 overall by rate with n>=30
pool = [h for h in hits if h["n"] >= 30]
pool.sort(key=lambda x: (-x["rate"], -x["n"]))
print("--- TOP n>=30 ---")
for h in pool[:20]:
    print("%s | %s | %d/%d=%.1f%% | h1 %.1f%% n=%d | h2 %.1f%% n=%d" % (
        h["outcome"], h["filters"], h["wins"], h["n"], 100 * h["rate"],
        100 * (h["h1"] or 0), h["h1_n"], 100 * (h["h2"] or 0), h["h2_n"],
    ))

# write extra csv
fields = ["filters", "outcome", "n", "wins", "rate", "h1_n", "h1_w", "h1", "h2_n", "h2_w", "h2", "claim"]
with (OUT / "buyable_grid.csv").open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for h in sorted(hits, key=lambda x: (-(x["rate"] or 0), -x["n"])):
        row = dict(h)
        for k in ("rate", "h1", "h2"):
            if row.get(k) is not None:
                row[k] = "%.4f" % row[k]
        w.writerow(row)
print("wrote buyable_grid.csv", len(hits))
if claims:
    print("CLAIMS:")
    for c in claims:
        print(c)
