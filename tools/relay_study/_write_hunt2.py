# -*- coding: utf-8 -*-
import csv
from collections import defaultdict
from pathlib import Path
import sys
sys.path.insert(0, r"D:\Ultra-Board\tools\relay_study")
import hunt_buyable2 as h

OUT = Path(r"D:\Ultra-Board\tools\relay_study\out")
cands, days, day_order, pos, bars = h.load_all()
dates = sorted({r["signal_date"] for r in cands if h.WINDOW_START <= r["signal_date"] <= h.WINDOW_END})
ths_cache, kpl_cache, theme_n, theme_members = h.load_day_extras(dates)
rows = h.enrich(cands, day_order, pos, bars, ths_cache, kpl_cache, theme_n)
first, second, all_dates = h.halves(rows)
ny = h.ny(rows)
mid_date = sorted(all_dates)[len(all_dates) // 2]


def pick_days(pool_pred):
    by = defaultdict(list)
    for r in ny:
        if pool_pred(r):
            by[r["date"]].append(r)
    picks = []
    for day, pool in sorted(by.items()):
        one = h.pick_one(pool, lambda r: r["seal"], True)
        if one:
            picks.append(one)
    return picks


A = pick_days(lambda r: r["boards"] == 3 and r["tn"] >= 8 and (not r["absent"]) and (not r["drop"]))
B = pick_days(lambda r: r["boards"] == 3 and r["tn"] >= 10 and r["H"] and r["boards"] < r["H"])
cA = h.cell(A, "maxc3", first, second)
cB = h.cell(B, "maxc3", first, second)

mfields = [
    "rule", "date", "code", "name", "theme", "boards", "H", "tn", "seal",
    "oc", "board_type", "px_t", "close1", "close2", "close3", "maxc3", "hold_close",
]
with (OUT / "name_pick_claim_members.csv").open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=mfields)
    w.writeheader()
    for rule, picks in (("A_board3_tn8_intact", A), ("B_board3_tn10_belowH", B)):
        for r in picks:
            w.writerow({
                "rule": rule, "date": r["date"], "code": r["code"], "name": r["name"],
                "theme": r["theme"], "boards": r["boards"], "H": r["H"], "tn": r["tn"],
                "seal": ("%.6f" % r["seal"]) if r["seal"] is not None else "",
                "oc": r["oc"], "board_type": r["board_type"],
                "px_t": r["px_t"], "close1": r["close1"], "close2": r["close2"],
                "close3": r["close3"], "maxc3": r["maxc3"], "hold_close": r["hold_close"],
            })

exist = list(csv.DictReader((OUT / "name_pick_cells.csv").open(encoding="utf-8-sig")))
fields = ["mode", "theme_n_min", "selector", "outcome", "n", "wins", "rate",
          "h1_n", "h1_w", "h1", "h2_n", "h2_w", "h2", "claim"]
extra = []
for mode, tnmin, sel, picks in (
    ("per_day", 8, "board3_intact_strongest", A),
    ("per_day", 10, "board3_belowH_strongest", B),
):
    for outcome in ("maxc3", "hold_close", "hold_flat", "hold_touch3",
                    "open_up", "open_flat", "touch3", "hold_zt3"):
        c = h.cell(picks, outcome, first, second)
        extra.append({
            "mode": mode, "theme_n_min": tnmin, "selector": sel, "outcome": outcome,
            "n": c["n"], "wins": c["wins"],
            "rate": ("%.4f" % c["rate"]) if c["rate"] is not None else "",
            "h1_n": c["h1_n"], "h1_w": c["h1_w"],
            "h1": ("%.4f" % c["h1"]) if c["h1"] is not None else "",
            "h2_n": c["h2_n"], "h2_w": c["h2_w"],
            "h2": ("%.4f" % c["h2"]) if c["h2"] is not None else "",
            "claim": c["claim"],
        })
# drop prior copies of these selectors if re-run
exist2 = [r for r in exist if r.get("selector") not in ("board3_intact_strongest", "board3_belowH_strongest")]
with (OUT / "name_pick_cells.csv").open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in exist2 + extra:
        w.writerow(r)


def member_table(picks):
    lines = [
        "| date | code | name | theme | H | tn | seal | oc | type | px_t | c1 | c2 | c3 | maxc3 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in picks:
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
            % (
                r["date"], r["code"], r["name"], r["theme"], r["H"], r["tn"],
                ("%.3f" % r["seal"]) if r["seal"] is not None else "",
                r["oc"], r["board_type"], r["px_t"], r["close1"], r["close2"],
                r["close3"], r["maxc3"],
            )
        )
    return "\n".join(lines)


def other_rates(picks):
    lines = []
    for ok in ("maxc3", "hold_close", "hold_flat", "hold_touch3", "hold_3d",
               "open_up", "open_flat", "touch3", "hold_zt3"):
        c = h.cell(picks, ok, first, second)
        lines.append("- %s: %s" % (ok, h.md_cell(c)))
    return "\n".join(lines)


md = []
md.append("# Buyable-path hunt 2")
md.append("")
md.append("Date: 2026-08-17. Historical frequencies only. Not a trading scheme.")
md.append("Win-rate bar remains 90% on BUYABLE fills. Yi-zi continuation is discarded, not optimized.")
md.append("Halves: first 2025-10-09..2026-03-12 / second 2026-03-13..2026-08-12 (mid_date=%s)." % mid_date)
md.append("")
md.append("## 0. CLAIMED 90% buyable stock rules")
md.append("")
md.append("Two name-pick rules hit n>=30, full-sample >=90%, both halves n>=15 and >=90%.")
md.append("Win is maxc3 (buy t close, max of next 3 closes > buy). Next-day hold_close is about 78%, not 90%.")
md.append("Filter-then-pick equals pick-then-veto on both cells (same members).")
md.append("All members re-read from out/daily_bars/{code}.json; stored maxc3 matches raw OHLC 42/42 and 46/46.")
md.append("No t-day yi-zi OHLC in either set. Selector uses t-known fields only.")
md.append("")
md.append("### Rule A -- 3-board strongest seal on intact crowded-theme days")
md.append("")
md.append("- Universe (t-known): not yi-zi, boards==3, own theme_n>=8, market intact (not height_drop) and leader still present (not leader_absent).")
md.append("- Selector: 1 name per day = max seal_order_ratio, tie-break code.")
md.append("- Buy: t close (THS limit_pool price, else bar close).")
md.append("- Win: max(t+1, t+2, t+3 close) > buy.")
md.append("- **39/42 = 92.9%**. half1 21/23 = 91.3%. half2 18/19 = 94.7%.")
md.append("- Losses (3): 2026-01-12 603017 Zhongheng Design; 2026-02-11 603980 Jihua; 2026-06-16 301176 Yihao.")
md.append("")
md.append(other_rates(A))
md.append("")
md.append(member_table(A))
md.append("")
md.append("### Rule B -- 3-board strongest seal, not the day high, theme_n>=10")
md.append("")
md.append("- Universe (t-known): not yi-zi, boards==3, own theme_n>=10, boards < H (not the day high).")
md.append("- Selector: 1 name per day = max seal_order_ratio, tie-break code.")
md.append("- Buy / win: same as A (t close / maxc3).")
md.append("- **42/46 = 91.3%**. half1 23/25 = 92.0%. half2 19/21 = 90.5%.")
md.append("- Losses (4): A's three plus 2026-07-03 605189 Fuchun.")
md.append("- Overlap with A: 32 names.")
md.append("")
md.append(other_rates(B))
md.append("")
md.append(member_table(B))
md.append("")
md.append("Honesty notes:")
md.append("")
md.append("- maxc3 is the mildest priced win (any of the next 3 closes beats t close). It is not next-day profit, not 3-day membership, not a daban fill.")
md.append("- hold_close on A is 33/42 = 78.6%; on B 36/46 = 78.3%. Those do not claim 90%.")
md.append("- strongest seal among that day's 3-boards can still be a weak ratio (several picks have seal < 1%).")
md.append("- The 38/46 grid cell (boards>=4 and seal>=2% and theme_n>=5, all such names, not 1-per-day) remains 82.6% after raw-bar verify. Not replaced; these are name-picks.")
md.append("")
md.append("## 1. Verify 38/46 cell against raw daily_bars")
md.append("")
md.append("Rebuilt independently from candidates + THS + daily_bars (same definition as grid_buyable).")
md.append("")
md.append("- n_base=46, n_with_maxc3=46")
md.append("- maxc3 38/46 = 82.6% | h1 23/28 = 82.1% | h2 15/18 = 83.3% | claim=False")
md.append("- raw daily_bars re-read spot-check: 13/13 match")
md.append("- THS price vs t bar close disagree (>0.02): 13/46. Buy uses THS (grid convention). Using bar close as buy yields 40/46 = 87.0%, still not 90%.")
md.append("- Number is correct. Not a scheme.")
md.append("")
md.append("8 losses of the 38/46 cell share no single t-known killer that keeps n>=30 at 90% (high turnover in 4/8 losses; turn 8-25 reaches 28/31 = 90.3% but half2 11/13 = 84.6%).")
md.append("")
md.append("## 2. Name pick (rest of the scan)")
md.append("")
md.append("Selectors were deterministic, t-known, yi-zi excluded. Modes: per_day / per_theme_day / per_day_max_theme. theme_n_min in {5,6,8,10,12}.")
md.append("Full grid: out/name_pick_cells.csv.")
md.append("")
md.append("Near-misses that failed a gate:")
md.append("")
md.append("| mode | tn | selector | outcome | n | rate | half1 | half2 | why not claim |")
md.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
md.append("| per_day_max_theme | 10 | tzi_strongest | maxc3 | 30 | 27/30=90.0% | 14/16=87.5% | 13/14=92.9% | half1<90, half2 n<15 |")
md.append("| per_day | 10 | board3_strongest | maxc3 | 55 | 48/55=87.3% | 23/26=88.5% | 25/29=86.2% | rate<90 |")
md.append("| per_day | 10 | board3_strongest + turn8-25 | maxc3 | 33 | 30/33=90.9% | 15/16=93.8% | 15/17=88.2% | half2<90 |")
md.append("| per_day_max_theme | 8 | tzi_strongest | maxc3 | 35 | 31/35=88.6% | 15/18=83.3% | 16/17=94.1% | rate<90 |")
md.append("")
md.append("T-zi t-bar check: 306 non-yi-zi T-zi names, 302 had a dip (low < close), 7 were OHLC-flat. Stock-level T-zi+theme_n is only 72-82%; the 90% T-zi cell was 1-per-day in the largest theme and failed halves.")
md.append("")
md.append("## 3. Squeeze the 82.6% neighborhood")
md.append("")
md.append("No squeeze cell hit 90% with n>=30 and both halves >=90%. Full grid: out/squeeze_cells.csv.")
md.append("")
md.append("Closest n>=30:")
md.append("")
md.append("| filters | outcome | n | rate | half1 | half2 |")
md.append("| --- | --- | --- | --- | --- | --- |")
md.append("| ge4_seal02_tn5+turn_mid (5-25) | maxc3 | 34 | 30/34=88.2% | 18/20=90.0% | 12/14=85.7% |")
md.append("| ge4_seal02_tn5+turn 8-25 | maxc3 | 31 | 28/31=90.3% | 17/18=94.4% | 11/13=84.6% |")
md.append("| ge3 unopened tn>=6 seal>=2% | maxc3 | 31 | 28/31=90.3% | 13/14=92.9% | 15/17=88.2% |")
md.append("| ge4_seal02_tn5+circ_mid | maxc3 | 37 | 32/37=86.5% | 20/23=87.0% | 12/14=85.7% |")
md.append("")
md.append("Breadcrumbs (both halves >=90% but n<30):")
md.append("")
md.append("- ge3 unopened tn>=6 + height_drop: 22/24 = 91.7% (10/11, 12/13)")
md.append("- ge3 unopened tn>=8 + height_drop: 20/22 = 90.9% (9/10, 11/12)")
md.append("")
md.append("Adding intact / broken / stronger seal / theme_n>=6/8 / not-zha / H-relative one-at-a-time to the 38/46 cell either drops below n=30 or stays in the mid-80s.")
md.append("")
md.append("## 4. Auction / daban / timeshare probe")
md.append("")
md.append("- THS: no auction/tick endpoint in repo. STOCK_LINE /v6/line/hs_{code}/01/ is daily OHLC only (already cached). Did not invent a minute period.")
md.append("- data/research/auction/observations.jsonl still empty. Contract forbids fabricating auction from close.")
md.append("- his_daban_list is NOT in the kaipanla backfill contract (backfill = sentiment / expression / zt_pool / sector_ladder only). No mass backfill.")
md.append("- Tiny probe (2 days, Type=4): KaipanlaClient.his_daban_list ReadTimeout 12s on 2026-07-24 and 2026-01-08. One-off retry 30s -> SSL EOF. No schema, no rows. Dumps: out/daban_probe/.")
md.append("- Field still missing for auction / huifeng daban fills: live or historically-verified auction prints, and timeshare / open-board prices.")
md.append("")
md.append("## 5. Files")
md.append("")
md.append("- out/buyable_hunt2.md (this file)")
md.append("- out/name_pick_cells.csv")
md.append("- out/name_pick_claim_members.csv")
md.append("- out/squeeze_cells.csv")
md.append("- out/daban_probe/ (timeouts only)")
md.append("- Prior outputs untouched: buyable_hunt.md, buyable_cells.csv, buyable_grid.csv, candidates.csv, daily_bars/")
md.append("- script: tools/relay_study/hunt_buyable2.py")
md.append("")

(OUT / "buyable_hunt2.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("A", h.md_cell(cA))
md_path = OUT / "buyable_hunt2.md"
print("B", h.md_cell(cB))
print("md", md_path.stat().st_size)
print("members", (OUT / "name_pick_claim_members.csv").stat().st_size)
print("csv rows", len(exist2) + len(extra))
