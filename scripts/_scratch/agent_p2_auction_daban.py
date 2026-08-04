# -*- coding: utf-8 -*-
"""P2 强竞价确认打板

选股：层内自然票成交额最大（非一字优先：若存在 amt>=5 非一字取其中额最大，否则全局额最大）
竞价门禁：open_pct_t1 >= 3.0 且 < 9.8；None → False
打板进场：common 统一
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auction_daban_common import OUT_DIR, build_nodes, run_strategy  # noqa: E402


def pick_p2(cands, node):
    """层内自然额最大；非一字 amt>=5 优先。"""
    if not cands:
        return None
    space = [c for c in cands if (not c.get("yizi")) and (c.get("amt") or 0) >= 5]
    pool = space if space else cands
    return max(pool, key=lambda x: (x.get("amt") or 0, -(x.get("seal_sec") or 10**9)))


def auction_ok(c, node) -> bool:
    op = c.get("open_pct_t1")
    if op is None:
        return False
    try:
        v = float(op)
    except (TypeError, ValueError):
        return False
    return 3.0 <= v < 9.8


def _brief_trade(t: dict) -> dict:
    return {
        "T": t.get("T"),
        "T1": t.get("T1"),
        "exit_day": t.get("exit_day"),
        "code": t.get("code"),
        "name": t.get("name"),
        "ret": t.get("ret"),
        "open_pct_t1": t.get("open_pct_t1"),
        "entry": t.get("entry"),
        "exit": t.get("exit"),
        "cont_days": t.get("cont_days"),
        "boards": t.get("boards"),
        "hit": t.get("hit"),
    }


def main():
    nodes, days, pools_m, day_i = build_nodes()
    res = run_strategy(
        "P2_强竞价确认打板",
        pick_p2,
        auction_filter=auction_ok,
        nodes=nodes,
        days=days,
        pools_m=pools_m,
        day_i=day_i,
    )
    ok = res.get("ok_trades") or []
    sorted_ok = sorted(ok, key=lambda x: x.get("ret") or 0.0, reverse=True)
    top10 = [_brief_trade(t) for t in sorted_ok[:10]]
    bottom10 = [_brief_trade(t) for t in sorted(ok, key=lambda x: x.get("ret") or 0.0)[:10]]

    out = {
        "name": res["name"],
        "n_signal": res["n_signal"],
        "n_ok": res["n_ok"],
        "n_skip": res["n_skip"],
        "n_abstain": res["n_abstain"],
        "skip_reasons": res["skip_reasons"],
        "mean_ret": res["mean_ret"],
        "median_ret": res["median_ret"],
        "win_rate": res["win_rate"],
        "sum_ret": res["sum_ret"],
        "compound_no_overlap": res["compound_no_overlap"],
        "final_equity": res["final_equity"],
        "n_no_overlap": res["n_no_overlap"],
        "n_hit_ok": res["n_hit_ok"],
        "hit_ok_mean": res["hit_ok_mean"],
        "top10": top10,
        "bottom10": bottom10,
        "trades": res["trades"],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "agent_p2_auction_daban.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== P2 强竞价确认打板 ===")
    print(f"n_ok={out['n_ok']}  n_no_overlap={out['n_no_overlap']}  n_hit_ok={out['n_hit_ok']}")
    print(f"mean_ret={out['mean_ret']:.4%}  win_rate={out['win_rate']:.2%}")
    print(f"sum_ret={out['sum_ret']:.4f}  compound_no_overlap={out['compound_no_overlap']:.4%}")
    print(f"final_equity={out['final_equity']:.4f}")
    print(f"skip_reasons={out['skip_reasons']}")
    print(f"wrote {path}")
    return out


if __name__ == "__main__":
    main()
