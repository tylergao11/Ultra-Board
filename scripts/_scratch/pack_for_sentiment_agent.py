# -*- coding: utf-8 -*-
"""Stage1 ML 分 → 打包给「真实情绪/题材」子 agent。

用法：
  python scripts/_scratch/pack_for_sentiment_agent.py --day 2025-10-30
  python scripts/_scratch/pack_for_sentiment_agent.py --day 2025-10-30 --top 8

输出：
  data/kaipanla/ladder_daily/agent_packs/{T}_ml_pack.json
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

import importlib.util
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ferment_open_seal_grid import theme_fb_counts, open_pct_t1

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "kaipanla" / "raw"
ML_CSV = ROOT / "data" / "kaipanla" / "ladder_daily" / "ml_cont_scores.csv"
LABELS = ROOT / "data" / "kaipanla" / "ladder_daily" / "human_labels_v1.json"
OUT_DIR = ROOT / "data" / "kaipanla" / "ladder_daily" / "agent_packs"
AGENT_SPEC = (
    ROOT / "scripts" / "_scratch" / "agents" / "sentiment_theme_scorer.md"
)


def theme_rank_map(stocks):
    fb = theme_fb_counts(stocks)
    items = sorted(fb.items(), key=lambda x: (-x[1], x[0]))
    rank, prev_c, prev_r = {}, None, 0
    for i, (th, c) in enumerate(items, 1):
        if c != prev_c:
            prev_r, prev_c = i, c
        rank[th] = prev_r
    return rank, fb, len(items)


def seal_hm(s):
    ts = s.get("first_limit_ts")
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%H:%M:%S")
    except Exception:
        return None


def load_ml_for_day(day: str) -> dict[str, dict]:
    if not ML_CSV.exists():
        return {}
    out = {}
    with ML_CSV.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("T") == day:
                out[row["code"].zfill(6)] = row
    return out


def load_sentiment(day: str) -> dict:
    p = RAW / day / "sentiment.json"
    if not p.exists():
        return {}
    try:
        j = json.loads(p.read_text(encoding="utf-8-sig"))
        info = j.get("info") or {}
        keys = (
            "ZT", "DT", "SJZT", "SJDT", "STZT", "STDT",
            "SZJS", "XDJS", "sign", "szln", "qscln",
        )
        return {k: info.get(k) for k in keys if k in info}
    except Exception:
        return {}


def load_expression(day: str):
    p = RAW / day / "expression.json"
    if not p.exists():
        return None
    try:
        j = json.loads(p.read_text(encoding="utf-8-sig"))
        return j.get("info")
    except Exception:
        return None


def pack_day(day: str, top: int = 12) -> Path:
    days, pools, pools_m = bt.load_days()
    if day not in days:
        raise SystemExit(f"no day {day}")
    i = days.index(day)
    if i < 1 or i + 1 >= len(days):
        raise SystemExit(f"day {day} has no prev/next")
    prev, t1 = days[i - 1], days[i + 1]

    ok, dead_h, dead, _ = bt.is_high_tier_dead(
        pools[prev], set(pools_m[day].keys()), prev
    )
    if not ok:
        raise SystemExit(f"{day} is not a node day under current rules")

    lad = bt.pick_ladder(pools[day], day)
    mem = lad.get("members") or set()
    ranks, fb, n_th = theme_rank_map(pools[day])
    ml = load_ml_for_day(day)
    an = lad.get("anchor") or {}

    cands = []
    for s in pools[day]:
        if s["code"] not in mem:
            continue
        if bt.is_gonggao(s, day):
            continue
        code = str(s["code"]).zfill(6)
        th = (s.get("theme") or "").strip() or "（无）"
        b = int(s.get("boards") or 0)
        s1 = pools_m.get(t1, {}).get(code)
        cont = bool(s1) and int(s1.get("boards") or 0) == b + 1
        m = ml.get(code) or {}
        cands.append(
            {
                "code": code,
                "name": s.get("name"),
                "boards": b,
                "theme_field": th,
                "ferment_rank_field": ranks.get(th, n_th + 1),
                "ferment_fb_field": fb.get(th, 0),
                "yizi": bt.is_yizi(s),
                "amount_yi": bt.amount_yi(s),
                "first_limit": seal_hm(s),
                "is_ladder_anchor": code == an.get("code"),
                "ml_score": float(m["score"]) if m.get("score") not in (None, "") else None,
                "ml_prob": float(m["prob"]) if m.get("prob") not in (None, "") else None,
                # T+1 仅供 agent 做执行层，标注为 next_day
                "next_day": {
                    "date": t1,
                    "open_pct": open_pct_t1(code, t1, s1),
                    "in_zt": s1 is not None,
                    "boards": int(s1["boards"]) if s1 else None,
                    "continued": cont,
                },
            }
        )

    cands.sort(
        key=lambda x: (
            -(x["ml_score"] if x["ml_score"] is not None else -1),
            -(x["amount_yi"] or 0),
        )
    )
    if top > 0:
        cands = cands[:top]

    principles = {}
    if LABELS.exists():
        principles = json.loads(LABELS.read_text(encoding="utf-8"))

    pack = {
        "stage": "ml_then_sentiment_agent",
        "T": day,
        "T1": t1,
        "node": {
            "dead_h": dead_h,
            "dead": [f"{d['name']}{d['boards']}" for d in dead],
            "ladder_anchor_type": lad.get("anchor_type"),
            "ladder_height": lad.get("height"),
            "ladder_anchor_name": an.get("name"),
        },
        "market_T": {
            "sentiment": load_sentiment(day),
            "expression": load_expression(day),
            "zt_count": len(pools[day]),
            "n_themes_with_first_board": n_th,
        },
        "market_T1_hint": {
            "sentiment": load_sentiment(t1),
            "expression": load_expression(t1),
        },
        "ml_candidates": cands,
        "human_principles": principles.get("principles")
        or [
            "only_best_in_ladder",
            "no_zero_ferment_near_limit_open",
            "abandon_if_cannot_touch_or_fill",
            "use_true_theme_story_not_raw_field_only",
        ],
        "agent_spec_path": str(AGENT_SPEC.relative_to(ROOT)),
        "instructions": (
            "Read scripts/_scratch/agents/sentiment_theme_scorer.md. "
            "Correct true themes, ferment rank, pick best-only, output agent_score JSON."
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{day}_ml_pack.json"
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True, help="节点日 YYYY-MM-DD")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()
    path = pack_day(args.day, top=args.top)
    print(f"wrote {path}")
    print(f"agent spec: {AGENT_SPEC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
