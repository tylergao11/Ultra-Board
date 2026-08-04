# -*- coding: utf-8 -*-
"""反推：从「走过自然最高」的连板路径 → 找它的节点日与当时梯队。

步骤：
1. 扫全样本，找出每一段「自然连板路径」及其曾达到的最大自然高度
2. 路径中曾成为 natural_max 成员的，记为「走到过最高」
3. 对每段路径，找启动后第一个「断板日」关系：
   - 路径在涨停池内的每个交易日 T，看 T 是否节点日（昨自然高死绝）
   - 记录断高 H、今日自然最高、路径票当日板数、是否在往下锚/顶锚
4. 输出：主升路径表 + 反推节点梯队 md/json，供后续研究切/冲
"""
from __future__ import annotations

import importlib.util
import json
from collections import defaultdict
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "kaipanla" / "ladder_daily"
OUT_MD = OUT_DIR / "reverse_leader_nodes.md"
OUT_JSON = OUT_DIR / "reverse_leader_nodes.json"


def build_paths(days, pools):
    """连续涨停路径：同 code 相邻交易日 boards 递增或连续在池。

    简单定义：在涨停池中 boards 从 1 起连续 +1 的片段。
    断板（不在池或 boards 重置）结束路径。
    """
    # code -> list of (day, stock)
    by_code: dict[str, list] = defaultdict(list)
    for d in days:
        for s in pools[d]:
            by_code[s["code"]].append((d, s))

    paths = []
    for code, events in by_code.items():
        events = sorted(events, key=lambda x: x[0])
        i = 0
        while i < len(events):
            d0, s0 = events[i]
            b0 = int(s0.get("boards") or 0)
            if b0 < 1:
                i += 1
                continue
            # start new path at this event
            seg = [(d0, s0)]
            j = i + 1
            while j < len(events):
                d1, s1 = events[j]
                b1 = int(s1.get("boards") or 0)
                prev_d, prev_s = seg[-1]
                pb = int(prev_s.get("boards") or 0)
                # 同一路径：后一日 boards == 前一日 boards+1（严格连板）
                # 允许隔日（休市）只要 boards 连续
                if b1 == pb + 1:
                    seg.append((d1, s1))
                    j += 1
                    continue
                break
            if len(seg) >= 2 or (len(seg) == 1 and int(seg[0][1].get("boards") or 0) >= 3):
                paths.append(
                    {
                        "code": code,
                        "name": seg[-1][1].get("name") or seg[0][1].get("name"),
                        "seg": seg,
                        "start": seg[0][0],
                        "end": seg[-1][0],
                        "max_boards": max(int(s.get("boards") or 0) for _, s in seg),
                        "len_days": len(seg),
                    }
                )
            i = j if j > i else i + 1
    return paths


def was_nat_high(path, days, pools):
    """路径期间是否某日进入 natural_max 层。"""
    day_idx = {d: i for i, d in enumerate(days)}
    hits = []
    for d, s in path["seg"]:
        if not bt.is_natural(s, d):
            continue
        mx, highs = bt.natural_max(pools[d], d)
        if mx <= 0:
            continue
        if s["code"] in {h["code"] for h in highs}:
            hits.append((d, int(s.get("boards") or 0), mx))
    return hits


def node_on(days, pools, pools_m, day):
    """day 是否节点日；返回 (ok, dead_h, dead_names, prev)"""
    if day not in {d: i for i, d in enumerate(days)}:
        return False, 0, [], None
    i = days.index(day)
    if i < 1:
        return False, 0, [], None
    prev = days[i - 1]
    ok, dead_h, dead, _ = bt.is_high_tier_dead(
        pools[prev], set(pools_m[day].keys()), prev
    )
    names = [f"{x['name']}{x['boards']}" for x in dead]
    return ok, dead_h, names, prev


def main():
    days, pools, pools_m = bt.load_days()
    paths = build_paths(days, pools)

    # 只保留：自然路径 且 曾成为自然最高
    leaders = []
    for p in paths:
        # 路径上至少一天 natural
        nat_days = sum(1 for d, s in p["seg"] if bt.is_natural(s, d))
        if nat_days == 0:
            continue
        hits = was_nat_high(p, days, pools)
        if not hits:
            continue
        p = dict(p)
        p["nat_high_hits"] = hits
        p["first_as_high"] = hits[0][0]
        p["max_as_high"] = max(h[1] for h in hits)
        p["peak_market_h"] = max(h[2] for h in hits)
        leaders.append(p)

    leaders.sort(key=lambda x: (-x["max_boards"], -x["len_days"], x["start"]))

    # 对每条 leader 路径：收集路径期内所有节点日，以及「首次成为最高」前最近节点
    rows = []
    height_pattern = defaultdict(int)  # (dead_h, boards_on_node) -> count
    rel_pattern = defaultdict(int)  # boards - dead_h
    near_patterns = defaultdict(int)

    for p in leaders:
        seg_days = {d for d, _ in p["seg"]}
        seg_map = {d: s for d, s in p["seg"]}
        nodes_in_path = []
        for d, s in p["seg"]:
            ok, dead_h, dead_names, prev = node_on(days, pools, pools_m, d)
            if not ok:
                continue
            b = int(s.get("boards") or 0)
            th, highs = bt.natural_max(pools[d], d)
            top_codes = {h["code"] for h in highs}
            lad = bt.pick_ladder(pools[d], d)
            down_codes = lad.get("members") or set()
            in_top = s["code"] in top_codes
            in_down = s["code"] in down_codes
            rel = b - dead_h if dead_h else None
            near = th is not None and dead_h and th >= dead_h - 1
            same_h_promo = dead_h and b == dead_h  # 断了 H，自己也在 H（同高反扑位）
            h_minus = dead_h and b == dead_h - 1

            rec = {
                "T": d,
                "dead_h": dead_h,
                "dead": dead_names,
                "boards": b,
                "theme": s.get("theme"),
                "amt": bt.amount_yi(s),
                "market_nat_h": th,
                "in_top": in_top,
                "in_down": in_down,
                "down_h": lad.get("height"),
                "rel": rel,
                "same_h": bool(same_h_promo),
                "h_minus1": bool(h_minus),
                "near_ceiling": bool(near),
                "yizi": bt.is_yizi(s),
            }
            nodes_in_path.append(rec)
            height_pattern[(dead_h, b)] += 1
            if rel is not None:
                rel_pattern[rel] += 1
            if same_h_promo:
                near_patterns["同高(断H自己H)"] += 1
            elif h_minus:
                near_patterns["H-1(断H自己H-1)"] += 1
            elif b < (dead_h or 0) - 1:
                near_patterns["更低(高低切位)"] += 1
            elif b > (dead_h or 0):
                near_patterns["高于断高"] += 1
            else:
                near_patterns["其他"] += 1

        # 首次成为自然最高之前/当日的最近节点
        first_high = p["first_as_high"]
        node_before = None
        for rec in nodes_in_path:
            if rec["T"] <= first_high:
                node_before = rec
        # 若首次最高当日不是节点，取路径内最后一个 <= first_high 的节点
        # 已在上面循环

        # 启动后第一个节点
        first_node = nodes_in_path[0] if nodes_in_path else None

        rows.append(
            {
                "name": p["name"],
                "code": p["code"],
                "start": p["start"],
                "end": p["end"],
                "max_boards": p["max_boards"],
                "first_as_high": p["first_as_high"],
                "max_as_high": p["max_as_high"],
                "path": [
                    f"{d}:{int(s['boards'])}" + ("Y" if bt.is_yizi(s) else "")
                    for d, s in p["seg"]
                ],
                "nodes": nodes_in_path,
                "first_node": first_node,
                "node_at_or_before_first_high": node_before,
            }
        )

    # ---- 写 md ----
    lines = []
    lines.append("# 反推：走到自然最高的连板 → 节点日梯队\n")
    lines.append(
        f"全样本路径中，**曾成为自然最高成员**的自然连板：**{len(rows)}** 段。\n"
    )
    lines.append(
        "节点日定义同现网：昨自然最高高度上自然票全灭（公告续板不续命）。\n"
    )

    lines.append("## 1. 反推分布：真主升在节点日站在哪（相对断高）\n")
    lines.append("统计对象：每条 leader 路径上**每一个**与其重叠的节点日（票当日 boards）。\n")
    total_node_touch = sum(height_pattern.values()) or 1
    lines.append("| 类型 | 次数 | 占比 |")
    lines.append("|------|------|------|")
    for k, v in sorted(near_patterns.items(), key=lambda x: -x[1]):
        lines.append(f"| {k} | {v} | {v/total_node_touch:.1%} |")
    lines.append("")
    lines.append("### boards − 断高 H\n")
    lines.append("| boards-H | 次数 |")
    lines.append("|----------|------|")
    for rel, c in sorted(rel_pattern.items()):
        lines.append(f"| {rel:+d} | {c} |")
    lines.append("")
    lines.append("### 断高 H × 当日 boards（热力）\n")
    # matrix top
    hs = sorted({h for h, b in height_pattern})
    bs = sorted({b for h, b in height_pattern})
    lines.append("| 断H\\\\板 | " + " | ".join(str(b) for b in bs) + " |")
    lines.append("|---|" + "|".join(["---"] * len(bs)) + "|")
    for h in hs:
        cells = [str(height_pattern.get((h, b), 0) or "") for b in bs]
        lines.append(f"| {h} | " + " | ".join(cells) + " |")
    lines.append("")

    # 首次成为最高时：前序节点特征
    lines.append("## 2. 「第一次成为自然最高」前最近节点\n")
    fb = [r for r in rows if r["node_at_or_before_first_high"]]
    lines.append(f"有前序/当日节点可挂的：**{len(fb)}/{len(rows)}**\n")
    same = sum(1 for r in fb if r["node_at_or_before_first_high"]["same_h"])
    hm = sum(1 for r in fb if r["node_at_or_before_first_high"]["h_minus1"])
    low = sum(
        1
        for r in fb
        if (r["node_at_or_before_first_high"]["rel"] or 0) <= -2
    )
    in_top = sum(1 for r in fb if r["node_at_or_before_first_high"]["in_top"])
    in_down = sum(1 for r in fb if r["node_at_or_before_first_high"]["in_down"])
    neither = sum(
        1
        for r in fb
        if not r["node_at_or_before_first_high"]["in_top"]
        and not r["node_at_or_before_first_high"]["in_down"]
    )
    lines.append("| 特征 | 次数 | 占比 |")
    lines.append("|------|------|------|")
    nfb = len(fb) or 1
    lines.append(f"| 同高反扑位 boards==H | {same} | {same/nfb:.1%} |")
    lines.append(f"| H-1 位 boards==H-1 | {hm} | {hm/nfb:.1%} |")
    lines.append(f"| 更低 boards≤H-2 | {low} | {low/nfb:.1%} |")
    lines.append(f"| 落在今日自然最高层 | {in_top} | {in_top/nfb:.1%} |")
    lines.append(f"| 落在往下锚层 | {in_down} | {in_down/nfb:.1%} |")
    lines.append(f"| 两层都不在 | {neither} | {neither/nfb:.1%} |")
    lines.append("")

    lines.append("## 3. 梯队脚本（按路径）\n")
    lines.append("每条：路径 → 相关节点日 → 当日位置（同高/H-1/更低）→ 是否在顶/底锚\n")

    # 只详细写 max_boards >= 5 的，其余摘要
    big = [r for r in rows if r["max_boards"] >= 5]
    lines.append(f"### 高标路径（max≥5板）共 {len(big)}\n")
    for r in big[:80]:
        lines.append(
            f"#### {r['name']}({r['code']}) {r['start']}→{r['end']} "
            f"最高{r['max_boards']}板 首登自然最高`{r['first_as_high']}`\n"
        )
        lines.append(f"- 路径: {' → '.join(r['path'])}\n")
        if not r["nodes"]:
            lines.append("- 路径期内**无节点日**（未碰上自然高死绝日）\n")
            continue
        for n in r["nodes"]:
            tag = []
            if n["same_h"]:
                tag.append("同高反扑位")
            if n["h_minus1"]:
                tag.append("H-1")
            if (n["rel"] or 0) <= -2:
                tag.append("更低/切")
            if n["in_top"]:
                tag.append("∈顶")
            if n["in_down"]:
                tag.append("∈往下")
            if not n["in_top"] and not n["in_down"]:
                tag.append("∉顶∉往下")
            lines.append(
                f"- 节点`{n['T']}` 断{n['dead_h']}({','.join(n['dead'][:3])}) "
                f"→ 本人**{n['boards']}板** 市场最高{n['market_nat_h']} "
                f"往下锚{n['down_h']} "
                f"[{','.join(tag)}] amt={n['amt']} theme={n['theme']}"
            )
        lines.append("")

    if len(big) > 80:
        lines.append(f"… 另有 {len(big)-80} 条高标路径见 JSON\n")

    lines.append("## 4. 给后续研究的含义\n")
    lines.append(
        "1. **同高/H-1** 占比高 → 「断了 H、下个四进五」是真实结构，对应**往上/反扑**\n"
        "2. **更低(≤H-2)** 占比高 → 断后从底起来，对应**往下/高低切**\n"
        "3. **∉顶∉往下** → 现锚规则漏斗有洞（节点日人还不在两套集合里）\n"
        "4. 下一步可按节点打标签：`同高反扑` / `H-1` / `深切`，再叠炸板率做切/冲\n"
    )

    # summary stats for console
    text = "\n".join(lines)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(text, encoding="utf-8")

    # JSON compact
    out_json = []
    for r in rows:
        out_json.append(
            {
                "name": r["name"],
                "code": r["code"],
                "start": r["start"],
                "end": r["end"],
                "max_boards": r["max_boards"],
                "first_as_high": r["first_as_high"],
                "path": r["path"],
                "nodes": r["nodes"],
                "node_before_first_high": r["node_at_or_before_first_high"],
            }
        )
    OUT_JSON.write_text(
        json.dumps(out_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"leaders={len(rows)} big5+={len(big)}")
    print("near_patterns", dict(near_patterns))
    print("first_high node: same", same, "h-1", hm, "low", low, "in_top", in_top, "in_down", in_down, "neither", neither)
    print(f"wrote {OUT_MD}")
    print(f"wrote {OUT_JSON}")
    # print head of md stats section
    print("\n".join(lines[:80]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
