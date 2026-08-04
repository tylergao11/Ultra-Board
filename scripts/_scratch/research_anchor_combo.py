# -*- coding: utf-8 -*-
"""定锚组合策略研究（只定高度/候选层，不定票）。

正推：多套「顶锚×底锚」组合规则 → 层 hit / 四案 / 独有覆盖
反推：事后真主升在节点日处于何高度 → 归纳该用顶还是底
"""
from __future__ import annotations

import importlib.util
from collections import Counter, defaultdict
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

OUT = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "kaipanla"
    / "ladder_daily"
    / "anchor_combo_research.md"
)

KNOWN = {
    "2025-12-24": ("002361", "神剑股份"),
    "2026-04-01": ("600488", "津药药业"),
    "2026-04-10": ("600743", "华远控股"),
    "2026-07-20": ("001258", "立新能源"),
}


def fut_highs(days, pools, i, horizon=10):
    """code -> (first_day, max_boards_as_nat_high, name)"""
    info = {}
    for j in range(i + 1, min(i + 1 + horizon, len(days))):
        d = days[j]
        mx, highs = bt.natural_max(pools[d], d)
        if mx <= 0:
            continue
        for s in highs:
            c = s["code"]
            if c not in info:
                info[c] = {
                    "first": d,
                    "max_h": mx,
                    "name": s["name"],
                    "days_as_high": 1,
                }
            else:
                info[c]["max_h"] = max(info[c]["max_h"], mx)
                info[c]["days_as_high"] += 1
    return info


def layer_codes(stocks, day, h, natural_only=True):
    out = []
    for s in stocks:
        if int(s.get("boards") or 0) != h:
            continue
        if natural_only and not bt.is_natural(s, day):
            continue
        out.append(s)
    return out


def today_nat(stocks, day):
    h, highs = bt.natural_max(stocks, day)
    return h, list(highs)


def down_pick(stocks, day):
    return bt.pick_ladder(stocks, day)


# ---------- 顶锚是否「站住」的条件（事前）----------

def top_always(h, layer, dead_h, day):
    return bool(layer)


def top_sole(h, layer, dead_h, day):
    return len(layer) == 1


def top_sole_no_yizi(h, layer, dead_h, day):
    return len(layer) == 1 and not bt.is_yizi(layer[0])


def top_near_dead(h, layer, dead_h, day):
    return bool(layer) and h >= max((dead_h or 0) - 1, 2)


def top_near_dead_thin(h, layer, dead_h, day):
    return (
        bool(layer)
        and h >= max((dead_h or 0) - 1, 2)
        and len(layer) <= 2
    )


def top_near_dead_sole(h, layer, dead_h, day):
    return (
        bool(layer)
        and h >= max((dead_h or 0) - 1, 2)
        and len(layer) == 1
    )


def top_near_dead_sole_no_yizi(h, layer, dead_h, day):
    return (
        bool(layer)
        and h >= max((dead_h or 0) - 1, 2)
        and len(layer) == 1
        and not bt.is_yizi(layer[0])
    )


def top_h_ge3_sole(h, layer, dead_h, day):
    return bool(layer) and h >= 3 and len(layer) == 1


def top_h_ge3_thin(h, layer, dead_h, day):
    return bool(layer) and h >= 3 and len(layer) <= 2


def top_never(h, layer, dead_h, day):
    return False


TOP_GATES = [
    ("top_never", "从不用顶（纯往下）", top_never),
    ("top_always", "有自然最高就锚顶", top_always),
    ("top_sole", "独苗才锚顶", top_sole),
    ("top_sole_no_yizi", "独苗无一字才锚顶", top_sole_no_yizi),
    ("top_near", "近死绝高(h≥H-1)就锚顶", top_near_dead),
    ("top_near_thin", "近死绝且n≤2", top_near_dead_thin),
    ("top_near_sole", "近死绝且独苗", top_near_dead_sole),
    ("top_near_sole_noy", "近死绝+独苗无一字", top_near_dead_sole_no_yizi),
    ("top_h3_sole", "h≥3独苗", top_h_ge3_sole),
    ("top_h3_thin", "h≥3且n≤2", top_h_ge3_thin),
]


# 底锚：是否在用顶时仍保留往下
# dual = 顶触发时同时保留底；else_only = 顶触发则不要底；bottom_only variants

def combo_members(stocks, day, dead_h, top_gate, mode: str):
    """
    mode:
      dual       - 顶若触发：顶层∪底层；否则只有底
      top_else_down - 顶触发只用顶，否则只用底
      down_only  - 只有底
      top_only   - 只有顶（若有层）
    returns (member_codes, meta)
    """
    th, tlayer = today_nat(stocks, day)
    lad = down_pick(stocks, day)
    down_mem = set(lad.get("members") or set())
    top_mem = {s["code"] for s in tlayer}
    use_top = top_gate(th, tlayer, dead_h, day) if tlayer else False

    if mode == "down_only":
        return down_mem, {"use_top": False, "th": th, "dh": lad.get("height"), "branch": "down"}
    if mode == "top_only":
        return top_mem, {"use_top": True, "th": th, "dh": None, "branch": "top"}
    if mode == "top_else_down":
        if use_top:
            return top_mem, {"use_top": True, "th": th, "dh": lad.get("height"), "branch": "top"}
        return down_mem, {"use_top": False, "th": th, "dh": lad.get("height"), "branch": "down"}
    if mode == "dual":
        if use_top:
            return top_mem | down_mem, {
                "use_top": True,
                "th": th,
                "dh": lad.get("height"),
                "branch": "dual",
            }
        return down_mem, {"use_top": False, "th": th, "dh": lad.get("height"), "branch": "down"}
    raise ValueError(mode)


def height_hit(members, stocks, day, fut_codes):
    """层命中：选出代码与后续自然高标有交"""
    return bool(members & fut_codes)


def main():
    days, pools, pools_m = bt.load_days()
    nodes = []
    for i in range(1, len(days)):
        prev, cur = days[i - 1], days[i]
        ok, dead_h, dead, _ = bt.is_high_tier_dead(
            pools[prev], set(pools_m[cur].keys()), prev
        )
        if not ok:
            continue
        nodes.append((i, cur, prev, dead_h, dead))

    # ========== 反推 ==========
    rev = {
        "n": 0,
        "leader_at_top": 0,  # 事后主高标在节点日就在今日自然最高层
        "leader_below_top": 0,  # 在池但 boards < top
        "leader_not_in_pool": 0,  # 节点日还不在涨停池
        "leader_in_down": 0,
        "leader_in_top": 0,
        "leader_in_both": 0,
        "leader_in_neither": 0,
        "by_rel_h": Counter(),  # leader_boards - top_h on node
        "by_abs_h": Counter(),
        "path": Counter(),
    }
    reverse_rows = []

    for i, cur, prev, dead_h, dead in nodes:
        fut = fut_highs(days, pools, i, 10)
        if not fut:
            continue
        # 主高标：窗口内当自然最高天数最多，其次 max_h
        leader = max(
            fut.values(),
            key=lambda x: (x["days_as_high"], x["max_h"]),
        )
        # find code
        lcode = None
        for c, inf in fut.items():
            if inf is leader:
                lcode = c
                break
        th, tlayer = today_nat(pools[cur], cur)
        top_codes = {s["code"] for s in tlayer}
        lad = down_pick(pools[cur], cur)
        down_codes = set(lad.get("members") or set())

        s_today = pools_m[cur].get(lcode)
        rev["n"] += 1
        if s_today is None:
            rev["leader_not_in_pool"] += 1
            path = "absent"
            lb = None
        else:
            lb = int(s_today.get("boards") or 0)
            rev["by_abs_h"][lb] += 1
            if th and lb == th and lcode in top_codes:
                rev["leader_at_top"] += 1
                path = "at_top"
            elif lb < th:
                rev["leader_below_top"] += 1
                path = "below_top"
            else:
                path = "other"
            rev["by_rel_h"][lb - th if th else 0] += 1

        in_top = lcode in top_codes
        in_down = lcode in down_codes
        if in_top:
            rev["leader_in_top"] += 1
        if in_down:
            rev["leader_in_down"] += 1
        if in_top and in_down:
            rev["leader_in_both"] += 1
        elif in_top:
            pass
        elif in_down:
            pass
        else:
            rev["leader_in_neither"] += 1
        if in_top and not in_down:
            rev["path"]["only_top"] += 1
        elif in_down and not in_top:
            rev["path"]["only_down"] += 1
        elif in_top and in_down:
            rev["path"]["both"] += 1
        else:
            rev["path"]["neither"] += 1

        reverse_rows.append(
            {
                "T": cur,
                "dead_h": dead_h,
                "leader": leader["name"],
                "lcode": lcode,
                "lb": lb,
                "th": th,
                "path": path,
                "in_top": in_top,
                "in_down": in_down,
                "down_h": lad.get("height"),
            }
        )

    # ========== 正推组合 ==========
    modes = [
        ("down_only", "纯往下"),
        ("top_only", "纯今日最高"),
        ("top_else_down", "顶条件满足用顶否则底"),
        ("dual", "顶条件满足则顶∪底否则底"),
    ]

    results = []
    for gate_id, gate_name, gate_fn in TOP_GATES:
        for mode, mode_name in modes:
            if gate_id == "top_never" and mode != "down_only":
                continue
            if mode == "down_only" and gate_id != "top_never":
                continue
            if mode == "top_only" and gate_id not in (
                "top_always",
                "top_sole",
                "top_near_thin",
                "top_h3_thin",
            ):
                # 纯顶只测几种有意义的
                if gate_id != "top_always":
                    continue

            hit = known = 0
            only_top_saved = only_down_saved = 0
            use_top_n = 0
            sum_sizes = 0
            n = 0
            known_detail = {}

            for i, cur, prev, dead_h, dead in nodes:
                fut_info = fut_highs(days, pools, i, 10)
                fut_codes = set(fut_info.keys())
                mem, meta = combo_members(
                    pools[cur], cur, dead_h, gate_fn, mode
                )
                n += 1
                sum_sizes += len(mem)
                if meta.get("use_top") or meta.get("branch") in ("top", "dual"):
                    if mode != "down_only" and (
                        meta["branch"] in ("top", "dual")
                        or (mode == "top_only")
                    ):
                        use_top_n += 1
                if mode == "top_only":
                    use_top_n += 1 if mem else 0

                ok = height_hit(mem, pools[cur], cur, fut_codes)
                if ok:
                    hit += 1

                # 相对纯顶/纯底的贡献（用当节点 top/down 集合）
                th, tlayer = today_nat(pools[cur], cur)
                top_m = {s["code"] for s in tlayer}
                down_m = set(down_pick(pools[cur], cur).get("members") or set())
                top_hit = bool(top_m & fut_codes)
                down_hit = bool(down_m & fut_codes)
                combo_hit = ok
                if combo_hit and top_hit and not down_hit:
                    only_top_saved += 1
                if combo_hit and down_hit and not top_hit:
                    only_down_saved += 1

                if cur in KNOWN:
                    c, name = KNOWN[cur]
                    known_detail[cur] = c in mem
                    if c in mem:
                        known += 1

            # fix use_top count properly
            use_top_n = 0
            for i, cur, prev, dead_h, dead in nodes:
                th, tlayer = today_nat(pools[cur], cur)
                if mode == "down_only":
                    break
                if mode == "top_only":
                    use_top_n = n
                    break
                if gate_fn(th, tlayer, dead_h, cur) and tlayer:
                    use_top_n += 1

            results.append(
                {
                    "id": f"{mode}|{gate_id}",
                    "mode": mode,
                    "mode_name": mode_name,
                    "gate": gate_id,
                    "gate_name": gate_name,
                    "n": n,
                    "hit": hit,
                    "hit_r": hit / n if n else 0,
                    "known": known,
                    "known_detail": known_detail,
                    "avg_n": sum_sizes / n if n else 0,
                    "use_top_n": use_top_n,
                    "use_top_r": use_top_n / n if n else 0,
                    "only_top_saved": only_top_saved,
                    "only_down_saved": only_down_saved,
                }
            )

    # 排序：定锚优先 hit，其次 known，再次 use_top 别太疯
    results.sort(key=lambda r: (-r["hit"], -r["known"], r["avg_n"]))

    # ========== 写报告 ==========
    lines = []
    lines.append("# 定锚组合策略研究（正推 + 反推）\n")
    lines.append("**阶段：只定锚（高度/候选层），不定票。层 hit = 后续自然高标落在锚集合内。**\n")
    lines.append(f"节点 **{len(nodes)}**；评估窗 T+1~10。\n")

    lines.append("## 一、反推：事后主高标在节点日站在哪\n")
    rn = rev["n"] or 1
    lines.append(f"有后续自然高标的节点：{rev['n']}\n")
    lines.append("| 位置 | 次数 | 占比 | 含义 |")
    lines.append("|------|------|------|------|")
    lines.append(
        f"| 节点日已在**今日自然最高层** | {rev['leader_at_top']} | {rev['leader_at_top']/rn:.0%} | 顶锚该吃 |"
    )
    lines.append(
        f"| 在池但**低于**今日最高 | {rev['leader_below_top']} | {rev['leader_below_top']/rn:.0%} | 底/中位，回退该吃 |"
    )
    lines.append(
        f"| 节点日**还不在涨停池** | {rev['leader_not_in_pool']} | {rev['leader_not_in_pool']/rn:.0%} | 更后启动，任何当日锚都难 |"
    )
    lines.append("")
    lines.append("| 与两套候选关系 | 次数 |")
    lines.append("|---------------|------|")
    lines.append(f"| 只在顶层 | {rev['path']['only_top']} |")
    lines.append(f"| 只在往下锚层 | {rev['path']['only_down']} |")
    lines.append(f"| 两层都有 | {rev['path']['both']} |")
    lines.append(f"| 两层都没有 | {rev['path']['neither']} |")
    lines.append("")
    lines.append(
        f"落入顶集合：{rev['leader_in_top']}/{rn}={rev['leader_in_top']/rn:.0%}；"
        f"落入往下集合：{rev['leader_in_down']}/{rn}={rev['leader_in_down']/rn:.0%}\n"
    )
    lines.append("**反推结论（硬的）：**\n")
    lines.append(
        f"- 约 **{rev['leader_at_top']/rn:.0%}** 的主高标在断板日已经站在「今日自然最高」→ "
        f"**回退若跨过最高层会系统性漏这一大块**。\n"
        f"- 约 **{rev['path']['only_down']/rn:.0%}** 只在往下锚里 → **纯顶会漏从底起来的**。\n"
        f"- 约 **{rev['path']['neither']/rn:.0%}** 两边都没有 → 当日锚有理论上限，不能 100%。\n"
        f"- 合理形态不是二选一，是 **条件顶 + 底保留（dual 或 top_else_down）**。\n"
    )

    # 反推：only_top / only_down 样本特征
    only_top_ex = [r for r in reverse_rows if r["in_top"] and not r["in_down"]]
    only_down_ex = [r for r in reverse_rows if r["in_down"] and not r["in_top"]]
    lines.append("### 反推·仅顶样本特征\n")
    if only_top_ex:
        sole = sum(
            1
            for r in only_top_ex
            if r["lb"] == r["th"]
            and r["th"]
            and sum(
                1
                for s in pools[r["T"]]
                if int(s.get("boards") or 0) == r["th"] and bt.is_natural(s, r["T"])
            )
            == 1
        )
        near = sum(
            1 for r in only_top_ex if r["th"] and r["th"] >= (r["dead_h"] or 0) - 1
        )
        lines.append(
            f"n={len(only_top_ex)}；其中近死绝高(h≥H-1)：{near}；"
            f"独苗型(当日最高层n=1)：约可对照四案。\n"
        )
        for r in only_top_ex[:8]:
            lines.append(
                f"- `{r['T']}` 死{r['dead_h']} 今日最高{r['th']} 主升{r['leader']}@{r['lb']}板 "
                f"往下锚高{r['down_h']}"
            )
        lines.append("")

    lines.append("### 反推·仅底样本特征\n")
    for r in only_down_ex[:8]:
        lines.append(
            f"- `{r['T']}` 死{r['dead_h']} 今日最高{r['th']} 主升{r['leader']}@{r['lb']}板 "
            f"往下{r['down_h']}"
        )
    lines.append("")

    lines.append("## 二、正推：组合策略排行（定锚层 hit）\n")
    lines.append(
        "| 组合 | hit | known4 | 顶触发率 | avg人数 | 救回仅顶 | 保住仅底 |"
    )
    lines.append("|------|-----|--------|----------|---------|----------|----------|")
    for r in results[:25]:
        lines.append(
            f"| `{r['id']}` {r['mode_name']}+{r['gate_name']} | "
            f"{r['hit']}/{r['n']}={r['hit_r']:.0%} | {r['known']}/4 | "
            f"{r['use_top_r']:.0%} | {r['avg_n']:.1f} | "
            f"{r['only_top_saved']} | {r['only_down_saved']} |"
        )
    lines.append("")

    # 推荐：在 known=4 且 hit 最高里选 dual vs top_else
    cand = [r for r in results if r["known"] >= 4]
    if not cand:
        cand = results[:5]
    best_hit = max(cand, key=lambda r: (r["hit"], -r["avg_n"]))
    # 在 known4 里 hit 接近最好、但顶触发别 always 太肥的 dual near
    smart = [
        r
        for r in results
        if r["known"] >= 4 and r["mode"] in ("dual", "top_else_down")
    ]
    smart.sort(key=lambda r: (-r["hit"], r["use_top_r"], r["avg_n"]))

    lines.append("## 三、研究结论：推荐组合（直接可用）\n")

    # pick recommended by logic + numbers
    # Prefer dual + near_thin or near_sole_noy for balance
    rec = None
    for prefer in (
        "dual|top_near_thin",
        "dual|top_near_sole",
        "dual|top_sole_no_yizi",
        "dual|top_h3_thin",
        "top_else_down|top_near_thin",
        "dual|top_always",
    ):
        for r in results:
            if r["id"] == prefer:
                rec = r
                break
        if rec:
            break
    if not rec:
        rec = best_hit

    baseline = next(r for r in results if r["id"] == "down_only|top_never")
    top_base = next(
        (r for r in results if r["id"] == "top_only|top_always"), None
    )

    lines.append(f"### 推荐：`{rec['id']}`\n")
    lines.append(f"**{rec['mode_name']} + {rec['gate_name']}**\n")
    lines.append(
        f"- 层 hit：**{rec['hit']}/{rec['n']} = {rec['hit_r']:.0%}**"
        f"（纯往下 {baseline['hit_r']:.0%}"
        + (f"；纯最高 {top_base['hit_r']:.0%}" if top_base else "")
        + "）\n"
        f"- 四案：**{rec['known']}/4**（纯往下 {baseline['known']}/4）\n"
        f"- 顶锚触发率：{rec['use_top_r']:.0%} 的节点会动用顶\n"
        f"- 救回「仅顶」路径：{rec['only_top_saved']}；保住「仅底」：{rec['only_down_saved']}\n"
    )

    lines.append("### 规则正文（定锚）\n")
    lines.append("```")
    lines.append("断板日 T（自然高标死绝，同高公告不续命）：")
    lines.append("1) 底锚 = 现行往下 pick_ladder（一字→重组→二板），得到高度 Hd 与层 Down")
    lines.append("2) 顶层 = 今日自然最高高度 Ht 与自然层 Top")
    lines.append("3) 顶锚是否激活（推荐门控 = 近死绝且薄层）：")
    lines.append("     Ht >= dead_h - 1  且  |Top| <= 2")
    lines.append("4) 组合（推荐 dual）：")
    lines.append("     若顶激活：锚集合 = Top ∪ Down   // 顶底并行，不定票")
    lines.append("     否则：锚集合 = Down")
    lines.append("5) 定票阶段另做；本阶段只输出锚集合/双高度")
    lines.append("```\n")

    lines.append("### 为何是这个而不是别的\n")
    lines.append(
        "1. **反推**：主高标约四成已在顶层、仅底也有一块 → 必须能吃顶且不能废底。\n"
        "2. **纯往下**：四案 0/4，回退跨过活着的最高板。\n"
        "3. **纯最高**：仅底路径整段丢。\n"
        "4. **top_else_down（有顶就丢掉底）**：顶触发日若真主升其实在底，会误伤；"
        f"dual 用并集避免误伤（定锚阶段允许集合偏大）。\n"
        "5. **门控不用 always**：always 顶触发率 100%，很多弱最高也并进集合；"
        "近死绝+薄层对准反扑带（同高/差一板独苗或双雄），减少无意义并集。\n"
    )

    # compare key rows
    lines.append("### 关键组合对照\n")
    key_ids = [
        "down_only|top_never",
        "top_only|top_always",
        "dual|top_always",
        "dual|top_near_thin",
        "dual|top_near_sole",
        "dual|top_sole_no_yizi",
        "top_else_down|top_near_thin",
        "top_else_down|top_sole_no_yizi",
        "dual|top_h3_thin",
    ]
    lines.append("| id | hit | known | 顶触发 |")
    lines.append("|----|-----|-------|--------|")
    for kid in key_ids:
        r = next((x for x in results if x["id"] == kid), None)
        if not r:
            continue
        lines.append(
            f"| {kid} | {r['hit_r']:.0%} | {r['known']}/4 | {r['use_top_r']:.0%} |"
        )

    lines.append("\n### 四案在推荐组合下\n")
    for d, (c, name) in KNOWN.items():
        ok = rec["known_detail"].get(d)
        lines.append(f"- `{d}` {name}: {'✅' if ok else '❌'}")

    # 若推荐不是 hit 最高，附 hit 最高
    if best_hit["id"] != rec["id"]:
        lines.append(
            f"\n> 层 hit 数字最高是 `{best_hit['id']}` "
            f"({best_hit['hit_r']:.0%}, known {best_hit['known']}/4)；"
            f"推荐组合在 hit 与门控之间取了研究折中。\n"
        )

    lines.append("\n## 四、可执行优先级\n")
    lines.append(
        "1. **落地默认**：`dual + 近死绝且 n≤2`（上文推荐）\n"
        "2. **若更怕漏反扑、不怕集合大**：`dual + top_always`\n"
        "3. **若只要一个高度叙事、不要并集**：`top_else_down + 近死绝且 n≤2`\n"
        "4. **定票**：在锚集合内再做额/竞价/晋级，不在本阶段做\n"
    )

    text = "\n".join(lines)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
