# -*- coding: utf-8 -*-
"""P1: 经典D选股 + 竞价门禁 [0, 9.5) 打板。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auction_daban_common import (  # noqa: E402
    OUT_DIR,
    pick_D,
    run_strategy,
)

NAME = "P1_classic_D_auction_0_9.5"


def auction_ok(cand, node) -> bool:
    """T+1 open_pct 在 [0, 9.5)：低开/平开到未竞价封死；None → skip。"""
    op = cand.get("open_pct_t1")
    if op is None:
        return False
    try:
        v = float(op)
    except (TypeError, ValueError):
        return False
    return 0.0 <= v < 9.5


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
    res = run_strategy(NAME, pick_D, auction_filter=auction_ok)
    ok = res.get("ok_trades") or []
    ranked = sorted(ok, key=lambda x: x.get("ret") or 0.0, reverse=True)
    top10 = [trade_brief(t) for t in ranked[:10]]
    bottom10 = [trade_brief(t) for t in ranked[-10:][::-1]] if ranked else []

    out = {
        "name": res["name"],
        "n_ok": res["n_ok"],
        "mean_ret": res["mean_ret"],
        "median_ret": res["median_ret"],
        "win_rate": res["win_rate"],
        "sum_ret": res["sum_ret"],
        "compound_no_overlap": res["compound_no_overlap"],
        "final_equity": res["final_equity"],
        "n_no_overlap": res["n_no_overlap"],
        "n_hit_ok": res["n_hit_ok"],
        "skip_reasons": res["skip_reasons"],
        "top10": top10,
        "bottom10": bottom10,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "agent_p1_auction_daban.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"[P1] n_ok={out['n_ok']} win={out['win_rate']:.1%} "
        f"mean={out['mean_ret']:+.2%} med={out['median_ret']:+.2%} "
        f"sum={out['sum_ret']:+.2%} compound={out['compound_no_overlap']:+.2%} "
        f"eq={out['final_equity']:.3f} n_no_ol={out['n_no_overlap']} "
        f"hit_ok={out['n_hit_ok']} skip={out['skip_reasons']} -> {out_path}"
    )
    return out_path


if __name__ == "__main__":
    main()
