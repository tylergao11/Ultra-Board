# -*- coding: utf-8 -*-
"""P5: 结构+竞价混合打板

选股：pick_D 为底；若 D 选出一字薄板(amt<3) 且层内存在非一字 amt>=5，
      改选非一字额最大（强制空间）。
竞价门禁分档：
  - 选中非一字：open_pct_t1 in [1.0, 9.5)
  - 选中一字(T日)：open_pct_t1 in [0, 7)
  - None → False
打板进场：common 统一
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auction_daban_common import (  # noqa: E402
    OUT_DIR,
    build_nodes,
    pick_D,
    run_strategy,
)

NAME = "P5_结构竞价混合打板"


def pick_p5(cands, node):
    """pick_D 为底；一字薄板(amt<3) 且有空间票时强制空间。"""
    if not cands:
        return None
    base = pick_D(cands, node)
    if base is None:
        return None
    # 一字薄板 + 层内存在非一字 amt>=5 → 改选非一字额最大
    if base.get("yizi") and (base.get("amt") or 0) < 3:
        space = [
            c
            for c in cands
            if (not c.get("yizi")) and (c.get("amt") or 0) >= 5
        ]
        if space:
            return max(
                space,
                key=lambda x: (
                    x.get("amt") or 0,
                    -(x.get("rank") or 999),
                    -(x.get("seal_sec") or 10**9),
                ),
            )
    return base


def auction_ok(cand, node) -> bool:
    """分档竞价门禁；None → False。"""
    op = cand.get("open_pct_t1")
    if op is None:
        return False
    try:
        v = float(op)
    except (TypeError, ValueError):
        return False
    # T 日是否一字决定档位
    if cand.get("yizi"):
        # 一字票：次日不能竞价过高
        return 0.0 <= v < 7.0
    # 非一字：需要一定竞价确认，且未封死
    return 1.0 <= v < 9.5


def trade_brief(t: dict) -> dict:
    return {
        "T": t.get("T"),
        "T1": t.get("T1"),
        "exit_day": t.get("exit_day"),
        "code": t.get("code"),
        "name": t.get("name"),
        "boards": t.get("boards"),
        "open_pct_t1": t.get("open_pct_t1"),
        "entry": t.get("entry"),
        "exit": t.get("exit"),
        "ret": t.get("ret"),
        "cont_days": t.get("cont_days"),
        "hit": t.get("hit"),
    }


def main():
    nodes, days, pools_m, day_i = build_nodes()
    res = run_strategy(
        NAME,
        pick_p5,
        auction_filter=auction_ok,
        nodes=nodes,
        days=days,
        pools_m=pools_m,
        day_i=day_i,
    )
    ok = res.get("ok_trades") or []
    ranked = sorted(ok, key=lambda x: x.get("ret") or 0.0, reverse=True)
    top10 = [trade_brief(t) for t in ranked[:10]]
    bottom10 = [trade_brief(t) for t in ranked[-10:][::-1]] if ranked else []

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
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "agent_p5_auction_daban.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"[P5] n_ok={out['n_ok']} win={out['win_rate']:.1%} "
        f"mean={out['mean_ret']:+.2%} med={out['median_ret']:+.2%} "
        f"sum={out['sum_ret']:+.2%} compound={out['compound_no_overlap']:+.2%} "
        f"eq={out['final_equity']:.3f} n_no_ol={out['n_no_overlap']} "
        f"hit_ok={out['n_hit_ok']} skip={out['skip_reasons']} -> {out_path}"
    )
    return out_path


if __name__ == "__main__":
    main()
