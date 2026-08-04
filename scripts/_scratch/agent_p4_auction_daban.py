# -*- coding: utf-8 -*-
"""P4 竞价相对最强打板

策略：
  1. 选股：层内 cands 优先有 open_pct_t1 的票，取 open_pct_t1 最高且 < 9.8
     （排除竞价一字）；并列比 amt；若全无 open_pct 则退回额最大
  2. 竞价门禁：open_pct_t1 is not None 且 -3 <= open_pct_t1 < 9.8
  3. 允许「带次日竞价」信息（复盘可知；实盘 9:25 后定票）

底座：auction_daban_common（断板节点 + 纯往下层 + 自然票 + 打板进场 + 断板卖）
输出：data/kaipanla/ladder_daily/agent_p4_auction_daban.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import auction_daban_common as adc  # noqa: E402

OUT = adc.OUT_DIR / "agent_p4_auction_daban.json"


def pick_p4(cands, node):
    """竞价相对最强：open_pct_t1 最高且 < 9.8；并列比额；全无 open_pct → 额最大。"""
    if not cands:
        return None
    eligible = [
        c
        for c in cands
        if c.get("open_pct_t1") is not None and float(c["open_pct_t1"]) < 9.8
    ]
    if eligible:
        return max(
            eligible,
            key=lambda x: (float(x["open_pct_t1"]), float(x.get("amt") or 0.0)),
        )
    # 全无 open_pct（eligible 空且无人有 pct），或全是竞价一字被排除 → 额最大
    return max(cands, key=lambda x: float(x.get("amt") or 0.0))


def auction_ok(c, node) -> bool:
    """门禁：有 open_pct_t1，且 -3 <= open_pct_t1 < 9.8。"""
    op = c.get("open_pct_t1")
    if op is None:
        return False
    try:
        v = float(op)
    except (TypeError, ValueError):
        return False
    return -3.0 <= v < 9.8


def main() -> int:
    nodes, days, pools_m, day_i = adc.build_nodes()
    res = adc.run_strategy(
        name="P4_竞价相对最强打板",
        pick_fn=pick_p4,
        auction_filter=auction_ok,
        nodes=nodes,
        days=days,
        pools_m=pools_m,
        day_i=day_i,
    )

    # 序列化（去掉不可 JSON 的对象；ret 保留 float）
    payload = {
        "name": res["name"],
        "strategy": {
            "id": "P4",
            "desc": "竞价相对最强打板：层内 open_pct_t1 最高且 <9.8；门禁 [-3, 9.8)",
            "pick": "max open_pct_t1 among <9.8, tiebreak amt; no open_pct → max amt",
            "auction_filter": "open_pct_t1 is not None and -3 <= open_pct_t1 < 9.8",
            "uses_t1_auction": True,
        },
        "n_nodes": len(nodes),
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
        "trades": res["trades"],
        "ok_trades": res["ok_trades"],
    }

    adc.OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== P4 竞价相对最强打板 ===")
    print(f"nodes={len(nodes)}  signals={res['n_signal']}  ok={res['n_ok']}  "
          f"skip={res['n_skip']}  abstain={res['n_abstain']}")
    print(f"skip_reasons={res['skip_reasons']}")
    print(f"mean_ret={res['mean_ret']:.4%}  median_ret={res['median_ret']:.4%}  "
          f"win_rate={res['win_rate']:.2%}  sum_ret={res['sum_ret']:.4%}")
    print(f"compound_no_overlap={res['compound_no_overlap']:.4%}  "
          f"final_equity={res['final_equity']:.4f}  n_no_overlap={res['n_no_overlap']}")
    print(f"n_hit_ok={res['n_hit_ok']}  hit_ok_mean={res['hit_ok_mean']:.4%}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
