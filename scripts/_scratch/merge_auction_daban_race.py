# -*- coding: utf-8 -*-
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "data" / "kaipanla" / "ladder_daily"

LABELS = [
    (1, "P1 经典D+竞价[0,9.5)"),
    (2, "P2 大额+强竞价[3,9.8)"),
    (3, "P3 发酵弱竞价[-2,5)"),
    (4, "P4 竞价相对最强"),
    (5, "P5 D强制空间+分档竞价"),
]


def main():
    rows = []
    for i, lab in LABELS:
        p = OUT / f"agent_p{i}_auction_daban.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        rows.append((lab, d))

    ranked = sorted(rows, key=lambda x: -float(x[1].get("final_equity") or 0))
    lines = [
        "# 次日竞价 + 打板进场 · 5 Agent 赛马",
        "",
        "统一底座：断板节点 + 往下锚层 + 自然票；**T+1 竞价(open_pct)** 门禁；**触板按涨停价打板**；持有到断板收盘。",
        "全天一字/未触板不成交。竞价量暂无，用 OHLC `open_pct` 代理。",
        "",
        "| 选手 | 成交 | 胜率 | 单笔均 | 加总 | **无重叠复利** | 终值 | 点对成交 | 主跳过 |",
        "|------|------|------|--------|------|----------------|------|----------|--------|",
    ]
    for lab, d in ranked:
        sk = d.get("skip_reasons") or {}
        parts = []
        for k, v in list(sk.items())[:3]:
            parts.append(f"{k.replace('skip_', '')}={v}")
        main = ",".join(parts)
        wr = float(d.get("win_rate") or 0) * 100
        mr = float(d.get("mean_ret") or 0) * 100
        sr = float(d.get("sum_ret") or 0) * 100
        cr = float(d.get("compound_no_overlap") or 0) * 100
        eq = float(d.get("final_equity") or 0)
        lines.append(
            f"| **{lab}** | {d.get('n_ok')} | {wr:.1f}% | {mr:.2f}% | {sr:.0f}% | "
            f"**{cr:.0f}%** | **{eq:.2f}x** | {d.get('n_hit_ok')} | {main} |"
        )

    champ_lab, champ = ranked[0]
    lines += [
        "",
        f"## 冠军：{champ_lab}",
        "",
        f"- 无重叠终值 **{float(champ.get('final_equity') or 0):.2f}x**"
        f"（复利 +{float(champ.get('compound_no_overlap') or 0)*100:.0f}%）",
        f"- 成交 {champ.get('n_ok')} 笔，胜率 {float(champ.get('win_rate') or 0)*100:.1f}%，"
        f"单笔均 {float(champ.get('mean_ret') or 0)*100:.2f}%",
        "",
        "## 策略一句话",
        "",
        "| ID | 选股 | 竞价门禁 |",
        "|----|------|----------|",
        "| P1 | pick_D 一字钉+换手空间 | open_pct ∈ [0, 9.5) |",
        "| P2 | 非一字大额优先 | [3.0, 9.8) |",
        "| P3 | 热发酵换手大额 | [-2, 5) 弱竞价捡漏 |",
        "| P4 | 层内竞价涨幅最高 | [-3, 9.8) |",
        "| P5 | D 但强制去薄一字 | 换手[1,9.5) / 一字T[0,7) |",
        "",
        "## 对比开盘买 D（上轮）",
        "",
        "上轮 D 开盘买→断板卖 无重叠约 **20.9x**；本轮打板进场更贵（涨停价），终值量级降到 **~4x** 属预期。",
        "",
        "明细：`agent_p1`…`agent_p5_auction_daban.json`",
        "脚本：`agent_p*_auction_daban.py` + `auction_daban_common.py`",
    ]
    text = "\n".join(lines)
    (OUT / "auction_daban_race.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
