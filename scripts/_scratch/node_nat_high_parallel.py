# -*- coding: utf-8 -*-
"""断板日并行：往下锚点 vs 当日自然最高板层"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "scripts/_scratch")
import backtest_main_ladder as bt

OUT = Path("data/kaipanla/ladder_daily/node_nat_high_parallel.md")


def natural_layer(stocks, day, h):
    return [s for s in stocks if int(s.get("boards") or 0) == h and bt.is_natural(s, day)]


def next_day(days, d):
    i = days.index(d)
    return days[i + 1] if i + 1 < len(days) else None


def promoted(s_today, pools, nd):
    """次日是否仍在涨停池且 boards+1"""
    if not nd or not s_today:
        return False
    code = s_today["code"]
    for s in pools.get(nd, []):
        if s["code"] == code:
            return int(s.get("boards") or 0) == int(s_today.get("boards") or 0) + 1
    return False


def main():
    days, pools, pools_m = bt.load_days()
    rows = []

    for i in range(1, len(days)):
        prev, cur = days[i - 1], days[i]
        dead_ok, dead_h, dead, alive = bt.is_high_tier_dead(
            pools[prev], set(pools_m[cur].keys()), prev
        )
        if not dead_ok:
            continue

        lad = bt.pick_ladder(pools[cur], cur)
        mx, highs = bt.natural_max(pools[cur], cur)
        nat_layer = natural_layer(pools[cur], cur, mx) if mx > 0 else []
        nat_layer = sorted(nat_layer, key=lambda s: -(bt.amount_yi(s) or 0))

        nd = next_day(days, cur)
        # 层内任一只次日晋级
        any_promo = any(promoted(s, pools, nd) for s in nat_layer)
        promo_names = [s["name"] for s in nat_layer if promoted(s, pools, nd)]

        # 事后：T+1~10 自然高标是否落在 自然最高层 / 往下锚层
        ti = days.index(cur)
        fut = bt.future_nat_highs(days, pools, ti + 1, 10) if ti + 1 < len(days) else []
        mem_down = lad["members"] or set()
        mem_nat = {s["code"] for s in nat_layer}
        hit_down, ev_down = bt.hit_members(mem_down, fut)
        hit_nat, ev_nat = bt.hit_members(mem_nat, fut)

        # 分类
        sole = len(nat_layer) == 1
        has_yizi = any(bt.is_yizi(s) for s in nat_layer)
        same_as_dead_h = mx == dead_h  # 同高反扑空间
        near_dead = mx == dead_h or mx == dead_h - 1

        # 往下锚是否等于自然最高层
        same_pick = lad.get("height") == mx

        rows.append(
            {
                "T": cur,
                "dead_h": dead_h,
                "dead": [f"{h['name']}{h['boards']}" for h in dead if bt.is_natural(h, prev)]
                or [f"{h['name']}{h['boards']}" for h in dead],
                "nat_h": mx,
                "nat_n": len(nat_layer),
                "nat_names": [s["name"] for s in nat_layer],
                "nat_detail": [
                    f"{s['name']}{s['boards']}/{bt.amount_yi(s)}亿"
                    f"{'[一字]' if bt.is_yizi(s) else ''}"
                    for s in nat_layer
                ],
                "sole": sole,
                "has_yizi": has_yizi,
                "same_as_dead_h": same_as_dead_h,
                "near_dead": near_dead,
                "any_promo": any_promo,
                "promo_names": promo_names,
                "down_type": lad.get("anchor_type"),
                "down_h": lad.get("height"),
                "down_anchor": (lad.get("anchor") or {}).get("name"),
                "same_pick": same_pick,
                "hit_down": hit_down,
                "hit_nat": hit_nat,
                "ev_nat": ev_nat,
                "ev_down": ev_down,
            }
        )

    n = len(rows)
    lines = []
    lines.append("# 断板日并行：往下锚点 vs 当日自然最高板\n")
    lines.append(f"节点 **{n}** 次。\n")
    lines.append(
        "- **往下锚**：现行 `pick_ladder`（≥3 自然一字/重组，否则二板…）\n"
        "- **自然最高板**：断板日当天 `natural_max` 整层（仅自然，公告不算进高度）\n"
        "- **晋级**：该层成员次日 boards+1 且仍在涨停池\n"
        "- **hit**：T+1~10 自然高标落在该层成员里\n"
    )

    # 总表统计
    sole_n = sum(r["sole"] for r in rows)
    promo_n = sum(r["any_promo"] for r in rows)
    sole_promo = sum(r["sole"] and r["any_promo"] for r in rows)
    near = sum(r["near_dead"] for r in rows)
    same_h = sum(r["same_as_dead_h"] for r in rows)
    no_yizi = sum(not r["has_yizi"] for r in rows)
    sole_no_yizi = sum(r["sole"] and not r["has_yizi"] for r in rows)
    sole_no_yizi_promo = sum(r["sole"] and not r["has_yizi"] and r["any_promo"] for r in rows)
    diverge = [r for r in rows if not r["same_pick"]]
    both_hit = sum(r["hit_down"] and r["hit_nat"] for r in rows)
    only_nat = sum(r["hit_nat"] and not r["hit_down"] for r in rows)
    only_down = sum(r["hit_down"] and not r["hit_nat"] for r in rows)
    neither = sum(not r["hit_down"] and not r["hit_nat"] for r in rows)

    lines.append("## 总览\n")
    lines.append("| 指标 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 节点数 | {n} |")
    lines.append(f"| 自然最高层 **独苗** | {sole_n}/{n} = {sole_n/n:.1%} |")
    lines.append(f"| 自然最高层 **有一字** | {sum(r['has_yizi'] for r in rows)}/{n} = {sum(r['has_yizi'] for r in rows)/n:.1%} |")
    lines.append(f"| 自然最高层 **无一字** | {no_yizi}/{n} = {no_yizi/n:.1%} |")
    lines.append(f"| 独苗且无一字 | {sole_no_yizi}/{n} = {sole_no_yizi/n:.1%} |")
    lines.append(f"| 自然最高 = 死绝高（同高空间） | {same_h}/{n} = {same_h/n:.1%} |")
    lines.append(f"| 自然最高 ∈ 死绝高或 h-1 | {near}/{n} = {near/n:.1%} |")
    lines.append(f"| 自然最高层 **次日有人晋级** | {promo_n}/{n} = {promo_n/n:.1%} |")
    lines.append(f"| 独苗 + 次日晋级 | {sole_promo}/{n} = {sole_promo/n:.1%} |")
    lines.append(f"| **独苗+无一字+次日晋级**（反扑候选） | {sole_no_yizi_promo}/{n} = {sole_no_yizi_promo/n:.1%} |")
    lines.append(f"| 往下锚高度 ≠ 自然最高 | {len(diverge)}/{n} = {len(diverge)/n:.1%} |")
    lines.append("")
    lines.append("### hit（T+1~10 自然高标∈层）\n")
    lines.append("| 结果 | 次数 | 占比 |")
    lines.append("|------|------|------|")
    lines.append(f"| 仅自然最高层命中 | {only_nat} | {only_nat/n:.1%} |")
    lines.append(f"| 仅往下锚命中 | {only_down} | {only_down/n:.1%} |")
    lines.append(f"| 两边都命中 | {both_hit} | {both_hit/n:.1%} |")
    lines.append(f"| 两边都不中 | {neither} | {neither/n:.1%} |")
    lines.append(f"| 自然最高层 hit | {sum(r['hit_nat'] for r in rows)}/{n} = {sum(r['hit_nat'] for r in rows)/n:.1%} |")
    lines.append(f"| 往下锚 hit | {sum(r['hit_down'] for r in rows)}/{n} = {sum(r['hit_down'] for r in rows)/n:.1%} |")
    lines.append(f"| **并集** hit | {sum(r['hit_nat'] or r['hit_down'] for r in rows)}/{n} = {sum(r['hit_nat'] or r['hit_down'] for r in rows)/n:.1%} |")
    lines.append("")

    # 分歧子集
    lines.append("## 高度分歧：往下锚 ≠ 自然最高\n")
    lines.append(f"共 **{len(diverge)}** 次。其中：\n")
    d_only_nat = sum(r["hit_nat"] and not r["hit_down"] for r in diverge)
    d_only_down = sum(r["hit_down"] and not r["hit_nat"] for r in diverge)
    d_both = sum(r["hit_nat"] and r["hit_down"] for r in diverge)
    d_none = sum(not r["hit_nat"] and not r["hit_down"] for r in diverge)
    d_sole_promo = sum(r["sole"] and r["any_promo"] for r in diverge)
    lines.append(f"- 仅自然最高 hit：{d_only_nat}")
    lines.append(f"- 仅往下锚 hit：{d_only_down}")
    lines.append(f"- 都 hit：{d_both}")
    lines.append(f"- 都不中：{d_none}")
    lines.append(f"- 分歧且独苗+晋级：{d_sole_promo}\n")

    lines.append("### 仅自然最高命中（往下锚漏、最高层抓到）\n")
    only_nat_rows = [r for r in rows if r["hit_nat"] and not r["hit_down"]]
    lines.append(f"共 {len(only_nat_rows)} 次：\n")
    for r in only_nat_rows:
        lines.append(
            f"- `{r['T']}` 死绝{r['dead_h']}({','.join(r['dead'][:3])}) "
            f"自然最高**{r['nat_h']}板** n={r['nat_n']} {'独苗' if r['sole'] else ''} "
            f"{','.join(r['nat_detail'])} "
            f"{'晋级:'+','.join(r['promo_names']) if r['any_promo'] else '未晋级'} "
            f"| 往下={r['down_type']}→{r['down_h']}板 {r['down_anchor']} "
            f"| 后高标={r['ev_nat']}"
        )
    lines.append("")

    lines.append("### 反扑候选：独苗 + 无一字 + 次日晋级\n")
    cand = [r for r in rows if r["sole"] and not r["has_yizi"] and r["any_promo"]]
    lines.append(f"共 {len(cand)} 次；hit_nat={sum(r['hit_nat'] for r in cand)}/{len(cand) or 1}\n")
    for r in cand:
        mark = ""
        names = ",".join(r["nat_names"])
        if any(x in names for x in ("立新能源", "津药", "华远")):
            mark = " **←已知错案**"
        lines.append(
            f"- `{r['T']}` 死绝{r['dead_h']}→自然最高**{r['nat_h']}** "
            f"{r['nat_detail'][0]} 晋级OK "
            f"| 往下={r['down_type']} {r['down_h']}板 {r['down_anchor']} "
            f"| same={r['same_pick']} hit_nat={r['hit_nat']} hit_down={r['hit_down']}{mark}"
        )
    lines.append("")

    # 三案特写
    lines.append("## 三案特写\n")
    focus = {
        "立新能源": ["2026-07-20", "2026-07-17"],
        "津药药业": ["2026-03-31", "2026-04-01"],
        "华远控股": ["2026-04-10"],
    }
    by_t = {r["T"]: r for r in rows}
    for name, ts in focus.items():
        lines.append(f"### {name}\n")
        for t in ts:
            r = by_t.get(t)
            if not r:
                lines.append(f"- `{t}` 非节点或不存在\n")
                continue
            in_nat = name in r["nat_names"]
            in_down = False
            # check down tier names via re-pick
            lad = bt.pick_ladder(pools[t], t)
            in_down = any(
                x.get("name") == name for x in (lad.get("tier") or [])
            )
            lines.append(
                f"- **`{t}`** 死绝{r['dead_h']}({','.join(r['dead'])})  \n"
                f"  自然最高 **{r['nat_h']}板** n={r['nat_n']}: {', '.join(r['nat_detail'])}  \n"
                f"  独苗={r['sole']} 一字={r['has_yizi']} 次日晋级={r['any_promo']}{r['promo_names']}  \n"
                f"  往下锚: {r['down_type']} → {r['down_h']}板 {r['down_anchor']}  \n"
                f"  **{name}∈自然最高层={in_nat}**；∈往下锚层={in_down}  \n"
                f"  hit_nat={r['hit_nat']} hit_down={r['hit_down']}\n"
            )

    lines.append("## 全表（简洁）\n")
    lines.append(
        "| T | 死绝h | 自然最高 | n | 独 | 晋 | 往下 | 同高 | hitN | hitD |\n"
        "|---|-------|----------|---|----|----|------|------|------|------|\n"
    )
    for r in rows:
        tag = []
        if r["sole"]:
            tag.append("独")
        if r["any_promo"]:
            tag.append("晋")
        if not r["has_yizi"]:
            tag.append("无Y")
        lines.append(
            f"| {r['T']} | {r['dead_h']} {','.join(r['dead'][:2])} | "
            f"{r['nat_h']} {','.join(r['nat_names'][:3])} | {r['nat_n']} | "
            f"{'Y' if r['sole'] else ''} | {'Y' if r['any_promo'] else ''} | "
            f"{r['down_h']}/{r['down_anchor']} | "
            f"{'Y' if r['same_pick'] else ''} | "
            f"{'Y' if r['hit_nat'] else ''} | {'Y' if r['hit_down'] else ''} |"
        )

    text = "\n".join(lines)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text[:6000])
    print("\n... [truncated] ...\n")
    # print key stats again
    print("=== KEY ===")
    print(f"nodes={n} sole={sole_n} sole_no_yizi_promo={sole_no_yizi_promo}")
    print(f"hit_nat={sum(r['hit_nat'] for r in rows)/n:.1%} hit_down={sum(r['hit_down'] for r in rows)/n:.1%} union={sum(r['hit_nat'] or r['hit_down'] for r in rows)/n:.1%}")
    print(f"only_nat={only_nat} only_down={only_down} diverge={len(diverge)}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
