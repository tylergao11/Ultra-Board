# -*- coding: utf-8 -*-
"""节点日清单：断谁 / 今日自然最高 / 往下锚（并行核对）。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)


def _amt(s: dict) -> str:
    a = bt.amount_yi(s)
    return f"{a}亿" if a is not None else "?"


def _tags(s: dict, day: str) -> str:
    t = []
    if bt.is_yizi(s):
        t.append("一字")
    if bt.is_gonggao(s, day):
        t.append("公告")
    return f"[{'+'.join(t)}]" if t else ""


def _one(s: dict, day: str) -> str:
    return f"{s['name']}{int(s['boards'])}板/{_amt(s)}{_tags(s, day)}"


def _layer(stocks: list, day: str) -> str:
    xs = sorted(stocks, key=lambda s: (-(bt.amount_yi(s) or 0), s["code"]))
    return " | ".join(_one(s, day) for s in xs)


def _next_day(days: list[str], d: str) -> str | None:
    i = days.index(d)
    return days[i + 1] if i + 1 < len(days) else None


def _promoted(s: dict, pools: dict, nd: str | None) -> bool:
    if not nd:
        return False
    b0 = int(s.get("boards") or 0)
    for t in pools.get(nd, []):
        if t["code"] == s["code"] and int(t.get("boards") or 0) == b0 + 1:
            return True
    return False


def main() -> int:
    days, pools, pools_m = bt.load_days()
    rows = []

    for i in range(1, len(days)):
        prev, cur = days[i - 1], days[i]
        dead_ok, dead_h, dead, _alive = bt.is_high_tier_dead(
            pools[prev], set(pools_m[cur].keys()), prev
        )
        if not dead_ok:
            continue

        # 断：只列昨自然最高上挂掉的自然票（已不含公告）
        dead_s = "、".join(f"{s['name']}{s['boards']}板" for s in dead)

        # ① 今日仍存活的自然最高层（不是死人，是断之后市场上的最高自然连板）
        today_h, today_highs = bt.natural_max(pools[cur], cur)
        nd = _next_day(days, cur)
        promo = [s for s in today_highs if _promoted(s, pools, nd)]
        sole = len(today_highs) == 1
        has_yizi = any(bt.is_yizi(s) for s in today_highs)
        fanpu = sole and (not has_yizi) and bool(promo)

        # ② 往下锚
        lad = bt.pick_ladder(pools[cur], cur)
        if lad["rule"] == "empty":
            continue
        an = lad["anchor"]
        down_h = lad["height"]
        same = down_h == today_h

        mark = ""
        if fanpu:
            mark = "  ⚡反扑候选"
        elif not same:
            mark = "  ↕分叉"

        note_bits = []
        if sole:
            note_bits.append("独苗")
        note_bits.append("有一字" if has_yizi else "无一字")
        if promo:
            note_bits.append("次日晋级 " + "、".join(s["name"] for s in promo))
        if fanpu:
            note_bits.append("反扑候选")
        if same:
            note_bits.append("与往下同高")
        else:
            note_bits.append(f"往下在{down_h}板")

        # 往下层内（brief 结构）
        tier_parts = []
        for x in lad["tier"]:
            a = x.get("amount_yi")
            a_s = f"{a}亿" if a is not None else "?"
            tg = []
            if x.get("is_yizi"):
                tg.append("一字")
            if x.get("is_gonggao"):
                tg.append("公告")
            t = f"[{'+'.join(tg)}]" if tg else ""
            tier_parts.append(f"{x['name']}{x['boards']}板/{a_s}{t}")

        rows.append(
            {
                "T": cur,
                "dead_h": dead_h,
                "dead_s": dead_s,
                "mark": mark,
                "today_h": today_h,
                "today_n": len(today_highs),
                "today_layer": _layer(today_highs, cur) if today_highs else "（无自然≥2板）",
                "today_note": "；".join(note_bits),
                "down_type": lad["anchor_type"],
                "down_anchor": (
                    f"{an['name']}{an['boards']}板/{an['amount_yi']}亿"
                    if an
                    else ""
                ),
                "down_h": down_h,
                "down_n": len(lad["members"]),
                "down_layer": " | ".join(tier_parts),
            }
        )

    out_path = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "kaipanla"
        / "ladder_daily"
        / "main_ladder_picks.md"
    )
    lines = [
        "# 节点日主升梯队候选（人工核对）",
        "",
        f"共 **{len(rows)}** 次。",
        "",
        "**断** = 昨自然最高 h 上的自然票今日都不在涨停池；同高公告续板不续命。",
        "",
        "每个节点三块，不重复：",
        "1. **断了谁**（昨天的自然高，已死）",
        "2. **今日自然最高**（断之后市场上还活着的自然最高层，不是死人）",
        "3. **往下锚**（现行 pick_ladder：有自然一字/重组才站住，否则回退）",
        "",
        "独苗+无一字+次日晋级 → **反扑候选**（晋级=事后标签）。",
        "",
    ]

    for i, r in enumerate(rows, 1):
        lines.append(
            f"### {i}. T=`{r['T']}`  断昨自然{r['dead_h']}板{r['mark']}"
        )
        lines.append("")
        lines.append(f"- **断了谁**：{r['dead_s']}")
        lines.append(
            f"- **今日自然最高**：{r['today_h']}板 n={r['today_n']}  〔{r['today_note']}〕"
        )
        lines.append(f"  - {r['today_layer']}")
        lines.append(
            f"- **往下锚** `{r['down_type']}`：{r['down_anchor']} → {r['down_h']}板 n={r['down_n']}"
        )
        lines.append(f"  - {r['down_layer']}")
        lines.append("")

    text = "\n".join(lines)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    # 只打 12 月中后几条方便看
    for r in rows:
        if r["T"] >= "2025-12-16" and r["T"] <= "2025-12-31":
            print(f"### T={r['T']} 断昨{r['dead_h']} {r['dead_s']}{r['mark']}")
            print(f"  今日最高{r['today_h']}: {r['today_layer']}")
            print(f"  往下{r['down_h']}: {r['down_anchor']}")
            print()
    print(f"共 {len(rows)} 节点 → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
