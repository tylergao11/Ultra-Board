# -*- coding: utf-8 -*-
"""次日竞价 + 打板进场 · 共用回测底座。

底座（用户规则）：
  - 断板节点 + 纯往下 pick_ladder + 仅自然票
  - 公告：连板路径任一天 theme 公告 → 全程公告

交易（本轮统一）：
  - 信号日 T 收盘后定票
  - 次日竞价：用 OHLC open_pct 作竞价涨幅%（无独立竞价量时的代理）
  - 打板进场：T+1 触及涨停价则按涨停价买入；全天一字 / 未触板 → 不成交
  - 持有到该票断板日（首次不在涨停池）收盘卖出

策略只实现：pick(cands, node) -> cand|None，以及可选 auction_ok(cand, t1_ctx)->bool
"""
from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

import importlib.util
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

from ferment_open_seal_grid import theme_fb_counts  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "kaipanla" / "ohlc_cache"
OUT_DIR = ROOT / "data" / "kaipanla" / "ladder_daily"

_bars: dict[str, dict] = {}


def load_bars(code: str) -> dict:
    code = str(code).zfill(6)
    if code in _bars:
        return _bars[code]
    p = CACHE / f"{code}.json"
    if not p.exists():
        _bars[code] = {}
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        _bars[code] = d.get("bars") or {}
    except Exception:
        _bars[code] = {}
    return _bars[code]


def bar(code: str, day: str) -> dict | None:
    b = load_bars(code).get(day)
    return b if b else None


def limit_pct_for(code: str, name: str = "") -> float:
    code = str(code).zfill(6)
    n = name or ""
    if "ST" in n.upper() or "st" in n:
        return 0.05
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


def limit_price(prev_close: float, code: str, name: str = "") -> float:
    return round(prev_close * (1.0 + limit_pct_for(code, name)), 2)


def is_all_day_yizi(open_v, high_v, low_v, close_v, tol: float = 0.02) -> bool | None:
    if None in (open_v, high_v, low_v, close_v):
        return None
    try:
        o, h, low, c = float(open_v), float(high_v), float(low_v), float(close_v)
    except (TypeError, ValueError):
        return None
    if min(o, h, low, c) <= 0:
        return None
    band = max(tol, abs(c) * 0.0015)
    return (
        abs(o - c) <= band
        and abs(h - c) <= band
        and abs(low - c) <= band
        and abs(h - low) <= band
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


def first_seal_sec(s):
    from datetime import datetime

    ts = s.get("first_limit_ts")
    if ts is None:
        return 10**9
    try:
        t = datetime.fromtimestamp(int(ts))
        return (t.hour - 9) * 3600 + (t.minute - 30) * 60 + t.second
    except Exception:
        return 10**9


def future_strength(code, b0, days, pools, pools_m, i0, horizon=10):
    max_b = b0
    nat_days = 0
    cont1 = False
    for j in range(i0 + 1, min(i0 + 1 + horizon, len(days))):
        d = days[j]
        s = pools_m[d].get(code)
        if not s:
            continue
        b = int(s.get("boards") or 0)
        max_b = max(max_b, b)
        if j == i0 + 1 and b == b0 + 1:
            cont1 = True
        mx, highs = bt.natural_max(pools[d], d)
        if mx > 0 and any(h["code"] == code for h in highs):
            nat_days += 1
    return nat_days * 1000 + max_b * 10 + (1 if cont1 else 0), max_b, nat_days, cont1


def build_nodes():
    days, pools, pools_m = bt.load_days()
    day_i = {d: i for i, d in enumerate(days)}
    nodes = []
    for i in range(1, len(days) - 1):
        prev, cur = days[i - 1], days[i]
        t1 = days[i + 1]
        ok, dead_h, dead, _ = bt.is_high_tier_dead(
            pools[prev], set(pools_m[cur].keys()), prev
        )
        if not ok:
            continue
        lad = bt.pick_ladder(pools[cur], cur)
        mem = lad.get("members") or set()
        ranks, fb, n_th = theme_rank_map(pools[cur])
        prev_map = pools_m[prev]
        raw = []
        for s in pools[cur]:
            if s["code"] not in mem:
                continue
            if bt.is_gonggao(s, cur) or not bt.is_natural(s, cur):
                continue
            code = s["code"]
            b0 = int(s.get("boards") or 0)
            amt = bt.amount_yi(s) or 0.0
            sp = prev_map.get(code)
            prev_amt = bt.amount_yi(sp) if sp else None
            prev_b = int(sp.get("boards") or 0) if sp else None
            if prev_amt and prev_amt > 0:
                vol_ratio = amt / prev_amt
            else:
                vol_ratio = None
            th = (s.get("theme") or "").strip() or "（无）"
            st, max_b, nat_d, cont1 = future_strength(
                code, b0, days, pools, pools_m, i
            )
            # T+1 竞价/OHLC
            b1 = bar(code, t1)
            s1 = pools_m.get(t1, {}).get(code)
            open_pct = None
            open_v = high_v = low_v = close_v = prev_v = None
            if b1:
                open_pct = b1.get("open_pct")
                open_v, high_v, low_v, close_v = (
                    b1.get("open"),
                    b1.get("high"),
                    b1.get("low"),
                    b1.get("close"),
                )
                prev_v = b1.get("prev_close")
                if open_pct is None and open_v is not None and prev_v:
                    try:
                        open_pct = (float(open_v) / float(prev_v) - 1.0) * 100.0
                    except Exception:
                        pass
            if s1 is not None:
                if open_pct is None and s1.get("open_pct") is not None:
                    try:
                        open_pct = float(s1["open_pct"])
                    except (TypeError, ValueError):
                        pass
                open_v = open_v if open_v is not None else s1.get("open")
                high_v = high_v if high_v is not None else s1.get("high")
                low_v = low_v if low_v is not None else s1.get("low")
                close_v = close_v if close_v is not None else s1.get("price")
                prev_v = prev_v if prev_v is not None else s1.get("prev_close")

            # T 收盘作次日 prev 的回退
            if prev_v is None and b1 is None:
                bt0 = bar(code, cur)
                if bt0 and bt0.get("close") is not None:
                    prev_v = bt0.get("close")

            yizi_t1 = is_all_day_yizi(open_v, high_v, low_v, close_v)
            if yizi_t1 is None and s1 is not None and bt.is_yizi(s1):
                yizi_t1 = True

            lp = None
            if prev_v is not None:
                try:
                    lp = limit_price(float(prev_v), code, s.get("name") or "")
                except Exception:
                    lp = None

            # 是否触及涨停（可打板）
            touch_limit = False
            if lp is not None and high_v is not None:
                try:
                    touch_limit = float(high_v) >= lp * 0.995
                except Exception:
                    touch_limit = False
            if s1 is not None and int(s1.get("boards") or 0) >= b0 + 1:
                touch_limit = True
            if s1 is not None and bt.is_yizi(s1):
                # 一字也算触板，但打板成交另判
                touch_limit = True

            raw.append(
                {
                    "code": code,
                    "name": s.get("name"),
                    "boards": b0,
                    "theme": th,
                    "rank": ranks.get(th, n_th + 1),
                    "fb": fb.get(th, 0),
                    "yizi": bt.is_yizi(s),
                    "amt": amt,
                    "seal_sec": first_seal_sec(s),
                    "is_anchor": code == (lad.get("anchor") or {}).get("code"),
                    "vol_ratio": vol_ratio,
                    "promoted": prev_b is not None and b0 == prev_b + 1,
                    "is_new": prev_amt is None,
                    "strength": st,
                    "fut_max_b": max_b,
                    "fut_nat_days": nat_d,
                    "cont1": cont1,
                    # T+1
                    "open_pct_t1": float(open_pct) if open_pct is not None else None,
                    "open_t1": open_v,
                    "high_t1": high_v,
                    "low_t1": low_v,
                    "close_t1": close_v,
                    "prev_t1": prev_v,
                    "limit_px_t1": lp,
                    "yizi_t1": yizi_t1,
                    "touch_limit_t1": touch_limit,
                    "in_zt_t1": s1 is not None,
                }
            )

        if not raw:
            continue
        max_amt = max(x["amt"] for x in raw) or 1e-6
        for x in raw:
            x["amt_share"] = x["amt"] / max_amt
            x["expand"] = x["vol_ratio"] is not None and x["vol_ratio"] > 1.25
            x["shrink"] = x["vol_ratio"] is not None and x["vol_ratio"] < 0.85

        best = max(raw, key=lambda x: x["strength"])
        has_gt = best["fut_nat_days"] > 0 or best["fut_max_b"] >= max(
            best["boards"] + 1, 3
        )
        if best["strength"] < 30 and best["fut_nat_days"] == 0:
            has_gt = False
        gt = None
        if has_gt:
            tops = [x for x in raw if x["strength"] == best["strength"]]
            gt = max(tops, key=lambda x: x["amt"])

        nodes.append(
            {
                "T": cur,
                "T1": t1,
                "dead_h": dead_h,
                "height": lad.get("height"),
                "anchor_type": lad.get("anchor_type"),
                "cands": raw,
                "gt": gt,
            }
        )
    return nodes, days, pools_m, day_i


def daban_entry(c) -> tuple[str, float | None]:
    """返回 (status, entry_price)。

    打板：触板且非全天一字 → 涨停价成交；
    全天一字 → skip_yizi；
    未触板 → skip_no_board；
    缺价 → skip_no_price。
    """
    if c.get("open_pct_t1") is None and c.get("open_t1") is None:
        return "skip_no_price", None
    if c.get("yizi_t1") is True:
        return "skip_yizi", None
    if not c.get("touch_limit_t1"):
        return "skip_no_board", None
    lp = c.get("limit_px_t1")
    if lp is None:
        # 回退：用 high 当板上价
        if c.get("high_t1") is not None:
            return "ok", float(c["high_t1"])
        return "skip_no_price", None
    return "ok", float(lp)


def exit_break(code: str, t1: str, days, pools_m, day_i) -> tuple[str | None, float | None, int]:
    """断板日收盘；返回 exit_day, exit_close, cont_days(含进场日在池天数)。"""
    code = str(code).zfill(6)
    i1 = day_i[t1]
    cont = 0
    for j in range(i1, len(days)):
        d = days[j]
        s = pools_m.get(d, {}).get(code)
        if s is not None:
            cont += 1
            continue
        bb = bar(code, d)
        cl = float(bb["close"]) if bb and bb.get("close") is not None else None
        return d, cl, cont
    d = days[-1]
    bb = bar(code, d)
    cl = float(bb["close"]) if bb and bb.get("close") is not None else None
    return d, cl, cont


def run_strategy(name: str, pick_fn, auction_filter=None, nodes=None, days=None, pools_m=None, day_i=None):
    """auction_filter(cand, node) -> bool；False 则本信号弃权。"""
    if nodes is None:
        nodes, days, pools_m, day_i = build_nodes()
    trades = []
    for node in nodes:
        cands = node["cands"]
        if not cands:
            continue
        pick = pick_fn(cands, node)
        if pick is None:
            trades.append({"T": node["T"], "status": "abstain", "hit": False})
            continue
        # 对齐最新 cand 字段
        c = next((x for x in cands if x["code"] == pick["code"]), pick)
        gt = node.get("gt")
        hit = bool(gt and gt["code"] == c["code"])

        if auction_filter is not None and not auction_filter(c, node):
            trades.append(
                {
                    "T": node["T"],
                    "T1": node["T1"],
                    "name": c["name"],
                    "code": c["code"],
                    "status": "skip_auction",
                    "hit": hit,
                    "open_pct_t1": c.get("open_pct_t1"),
                }
            )
            continue

        st, entry = daban_entry(c)
        if st != "ok":
            trades.append(
                {
                    "T": node["T"],
                    "T1": node["T1"],
                    "name": c["name"],
                    "code": c["code"],
                    "status": st,
                    "hit": hit,
                    "open_pct_t1": c.get("open_pct_t1"),
                }
            )
            continue

        exit_day, exit_close, cont = exit_break(
            c["code"], node["T1"], days, pools_m, day_i
        )
        if exit_close is None or entry is None or entry <= 0:
            trades.append(
                {
                    "T": node["T"],
                    "T1": node["T1"],
                    "name": c["name"],
                    "code": c["code"],
                    "status": "skip_no_exit",
                    "hit": hit,
                    "entry": entry,
                }
            )
            continue

        ret = exit_close / entry - 1.0
        trades.append(
            {
                "T": node["T"],
                "T1": node["T1"],
                "exit_day": exit_day,
                "name": c["name"],
                "code": c["code"],
                "status": "ok",
                "hit": hit,
                "open_pct_t1": c.get("open_pct_t1"),
                "entry": round(entry, 3),
                "exit": round(exit_close, 3),
                "ret": ret,
                "cont_days": cont,
                "boards": c["boards"],
            }
        )
    return summarize(name, trades)


def summarize(name: str, trades: list[dict]) -> dict:
    ok = [t for t in trades if t.get("status") == "ok"]
    sk = [t for t in trades if t.get("status") not in ("ok", "abstain")]
    ab = [t for t in trades if t.get("status") == "abstain"]
    rets = [t["ret"] for t in ok]
    hit_ok = [t for t in ok if t.get("hit")]
    n_sig = len(trades)

    # 无重叠满仓
    sorted_ok = sorted(ok, key=lambda x: (x.get("T1") or "", x.get("code") or ""))
    eq = 1.0
    free = ""
    taken = 0
    for t in sorted_ok:
        if free and (t.get("T1") or "") <= free:
            continue
        eq *= 1 + t["ret"]
        free = t.get("exit_day") or ""
        taken += 1

    # 点对率（有 GT 的节点上选对；用 hit 标记）
    decided = [t for t in trades if t.get("status") != "abstain"]
    # rough labeled
    mean_r = statistics.mean(rets) if rets else 0.0
    med_r = statistics.median(rets) if rets else 0.0
    win = sum(1 for r in rets if r > 0) / len(rets) if rets else 0.0
    sum_r = sum(rets) if rets else 0.0

    return {
        "name": name,
        "n_signal": n_sig,
        "n_ok": len(ok),
        "n_skip": len(sk),
        "n_abstain": len(ab),
        "skip_reasons": dict(Counter(t.get("status") for t in sk)),
        "mean_ret": mean_r,
        "median_ret": med_r,
        "win_rate": win,
        "sum_ret": sum_r,
        "compound_no_overlap": eq - 1.0,
        "final_equity": eq,
        "n_no_overlap": taken,
        "n_hit_ok": len(hit_ok),
        "hit_ok_mean": statistics.mean([t["ret"] for t in hit_ok]) if hit_ok else 0.0,
        "trades": trades,
        "ok_trades": ok,
    }


# ---- 经典 D 选股（可复用）----
def pick_D(cands, node):
    yizi = [c for c in cands if c["yizi"]]
    space = [c for c in cands if (not c["yizi"]) and c["amt"] >= 5]
    if yizi and space:
        space2 = [c for c in space if c["rank"] <= 15]
        pool = space2 if space2 else space
        return max(pool, key=lambda x: (x["amt"], -x["rank"], -x["seal_sec"]))
    if yizi and not space:
        return min(yizi, key=lambda x: (x["seal_sec"], -x["amt"]))
    return max(cands, key=lambda x: (x["amt"], -x["seal_sec"]))
