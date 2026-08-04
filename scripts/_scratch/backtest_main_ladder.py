# -*- coding: utf-8 -*-
"""定梯队：锚点 + 所在板高整层=梯队。

公告板判定：只看开盘啦主属性 theme（不用 concepts 概念堆）：
  重组 / 并购 / 实控人变更 / 股权转让 / 举牌 等
  连板路径上任意一天 theme 是公告 → 全程公告。

断自然高标（节点）：
  昨自然最高高度 h 上的**自然票**今日均不在涨停池 → 断。
  同高**公告**（实控人/并购重组等）续板 **不能**把自然高标续成「没断」
  （例：鹭燕5自然断、嘉美同5实控人续 → 仍算断 → 次日神剑接最高）。
  同高还有**自然**续板 → 不算断（例：远大5掉、大有同5续6 → 未断）。

定梯队（T 日）：
  - 逐层从上往下：有自然一字→锚一字；否则有重组→锚重组；整层全公告跳过
  - 都没有 → 二板整层
  - 梯队 = 锚点所在板高整层
  - 量能 = 成交额亿
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "kaipanla" / "raw"

# 公告板：只认开盘啦【主属性 theme】，不认 concepts（接口概念堆，App 主属性栏没有）
GONGGAO_KEYS = (
    "并购重组",
    "股权转让",
    "实控人变更",
    "实控人",
    "并购",
    "重组",
    "举牌",
)


def theme_text(s: dict) -> str:
    return (s.get("theme") or "").strip()


def is_gonggao_raw(s: dict) -> bool:
    """仅看当日主属性 theme。"""
    t = theme_text(s)
    return any(k in t for k in GONGGAO_KEYS)


def is_reorg(s: dict) -> bool:
    """重组类公告锚点：主属性命中。"""
    t = theme_text(s)
    keys = ("并购", "重组", "实控人", "股权转让")
    return any(k in t for k in keys)


# 连板粘性：路径上任一天是公告，全程当公告（theme 会漂）
# day -> code -> stock；由 load 后注入
_POOLS_BY_DAY: dict[str, dict[str, dict]] = {}
_DAYS_ORDER: list[str] = []


def _board_path(s: dict, day: str) -> list[tuple[str, dict]]:
    """本轮连板路径（旧→新），按 boards 1..今日接龙；跳过不在池的交易日。"""
    if day not in _POOLS_BY_DAY:
        return [(day, s)] if day else []
    code = s.get("code")
    if not code:
        return [(day, s)]
    try:
        bi = _DAYS_ORDER.index(day)
    except ValueError:
        return [(day, s)]
    chain_rev: list[tuple[str, dict]] = [(day, s)]
    expect = int(s.get("boards") or 0) - 1
    for j in range(bi - 1, -1, -1):
        if expect < 1:
            break
        d = _DAYS_ORDER[j]
        prev = _POOLS_BY_DAY[d].get(code)
        if not prev:
            continue
        pb = int(prev.get("boards") or 0)
        if pb != expect:
            if pb > expect:
                continue
            break
        chain_rev.append((d, prev))
        expect = pb - 1
    chain_rev.reverse()
    return chain_rev


def is_gonggao(s: dict, day: str | None = None) -> bool:
    """是否按「公告板」处理（只认主属性 theme，不用 concepts）。

    规则：
    - 本轮连板路径上 **任意一天** theme 是公告 → **全程公告**
      （后面漂回题材也仍算公告；中途某天并购/实控人也整段算公告）
    - 路径上从未出现公告 theme → 自然
    """
    if not day or day not in _POOLS_BY_DAY:
        return is_gonggao_raw(s)

    path = _board_path(s, day)
    if not path:
        return is_gonggao_raw(s)

    return any(is_gonggao_raw(st) for _, st in path)


def is_natural(s: dict, day: str | None = None) -> bool:
    return not is_gonggao(s, day)


def is_yizi(s: dict) -> bool:
    """一字：优先开盘啦首封 09:25 + r17≈0（业务口径）。

    东财 OHLC 有时 open=high=low 但 close 不一致，不能反过来否决开盘啦一字。
    """
    ts = s.get("first_limit_ts")
    raw = s.get("raw") or []
    if ts is not None and len(raw) > 17:
        try:
            t = datetime.fromtimestamp(int(ts))
            amp = float(raw[17] or 0)
            if t.hour == 9 and t.minute == 25 and amp <= 0.01:
                return True
        except Exception:
            pass
    # 回退：完整 OHLC 一字
    try:
        o, h, low, c = s.get("open"), s.get("high"), s.get("low"), s.get("price")
        if None not in (o, h, low, c):
            o, h, low, c = float(o), float(h), float(low), float(c)
            tol = 0.015
            return abs(o - c) <= tol and abs(h - c) <= tol and abs(low - c) <= tol
    except Exception:
        pass
    return False


def amount_yi(s: dict) -> float | None:
    raw = s.get("raw") or []
    if len(raw) > 11:
        try:
            return round(float(raw[11]) / 1e8, 2)
        except Exception:
            return None
    return None


def load_days():
    global _POOLS_BY_DAY, _DAYS_ORDER
    days = sorted(p.name for p in RAW.iterdir() if (p / "zt_pool.json").exists())
    pools, pools_m = {}, {}
    for d in days:
        stocks = json.loads((RAW / d / "zt_pool.json").read_text(encoding="utf-8-sig"))[
            "stocks"
        ]
        pools[d] = stocks
        pools_m[d] = {s["code"]: s for s in stocks}
    _DAYS_ORDER = days
    _POOLS_BY_DAY = pools_m
    return days, pools, pools_m


def ge2(stocks: list) -> list:
    return [s for s in stocks if int(s.get("boards") or 0) >= 2]


def natural_ge2(stocks: list, day: str | None = None) -> list:
    return [s for s in ge2(stocks) if is_natural(s, day)]


def natural_max(stocks: list, day: str | None = None) -> tuple[int, list]:
    """只看自然高标，公告板再高也不算（含连板粘性公告）。"""
    n = natural_ge2(stocks, day)
    if not n:
        return 0, []
    mx = max(int(s["boards"]) for s in n)
    return mx, [s for s in n if int(s["boards"]) == mx]


def high_tier_layer(stocks: list, height: int) -> list:
    """板高 = height 的整层（含公告；展示用）。"""
    return [s for s in stocks if int(s.get("boards") or 0) == height]


def is_high_tier_dead(
    prev_stocks: list,
    cur_code_set: set[str],
    prev_day: str | None = None,
) -> tuple[bool, int, list, list]:
    """自然高标是否死绝（出节点）。

    只看昨自然最高高度 h 上的**自然票**：
      全部不在今日涨停池 → 断。
    同高公告续板不续命（嘉美实控人 ≠ 鹭燕自然高还活着）。
    返回 dead/alive 也只含自然侧成员。
    """
    mx, nat_highs = natural_max(prev_stocks, prev_day)
    if mx <= 0:
        return False, 0, [], []
    # 自然侧同高 = nat_highs（已过滤公告）
    layer = list(nat_highs)
    alive = [s for s in layer if s["code"] in cur_code_set]
    dead = [s for s in layer if s["code"] not in cur_code_set]
    return (len(alive) == 0 and len(layer) > 0), mx, dead, alive


def layer_all_gonggao(layer: list, day: str | None = None) -> bool:
    return bool(layer) and all(is_gonggao(s, day) for s in layer)


def _brief(s: dict, day: str | None = None) -> dict:
    return {
        "code": s["code"],
        "name": s["name"],
        "boards": int(s["boards"]),
        "theme": s.get("theme") or "",
        "amount_yi": amount_yi(s),
        "is_yizi": is_yizi(s),
        "is_gonggao": is_gonggao(s, day),
        "is_reorg": is_reorg(s),
        "is_natural": is_natural(s, day),
    }


def pick_ladder(stocks: list, day: str | None = None) -> dict:
    """
    从上往下按「板高」逐层看：
      该层有自然一字 → 锚一字，梯队=该层整层
      否则该层有重组(公告) → 锚重组，梯队=该层整层
      整层全公告 → 跳过
    上面都没有 → 二板整层；再没有 → 最高非全公告层兜底。

    「有自然一字才锚一字，否则再找重组」= 在同一层内的优先顺序，不是全市场先扫完所有一字。
    """
    g = ge2(stocks)
    empty = {
        "rule": "empty",
        "anchor_type": None,
        "anchor": None,
        "height": None,
        "tier": [],
        "members": set(),
        "detail": "",
    }
    if not g:
        return empty

    by_h: dict[int, list] = defaultdict(list)
    for s in g:
        by_h[int(s["boards"])].append(s)
    heights = sorted(by_h.keys(), reverse=True)

    def make_tier(h: int, rule: str, anchor: dict) -> dict | None:
        layer_raw = by_h.get(h) or []
        if layer_all_gonggao(layer_raw, day):
            return None
        layer = [_brief(s, day) for s in layer_raw]
        layer.sort(key=lambda x: (-(x["amount_yi"] or 0), x["code"]))
        return {
            "rule": rule,
            "anchor_type": rule,
            "anchor": anchor,
            "height": h,
            "tier": layer,
            "members": {x["code"] for x in layer},
            "detail": (
                f"锚点={anchor['name']}{anchor['boards']}板/"
                f"{anchor['amount_yi']}亿 → 梯队={h}板整层 n={len(layer)}"
            ),
        }

    # 从上往下逐层：先自然一字，否则重组
    for h in heights:
        layer = by_h[h]
        if layer_all_gonggao(layer, day):
            continue

        nat_yizi = [s for s in layer if is_natural(s, day) and is_yizi(s)]
        if nat_yizi:
            nat_yizi.sort(key=lambda s: -(amount_yi(s) or 0))
            out = make_tier(h, "anchor_nat_yizi", _brief(nat_yizi[0], day))
            if out:
                return out

        reorgs = [s for s in layer if is_reorg(s)]
        if reorgs:
            reorgs.sort(key=lambda s: -(amount_yi(s) or 0))
            out = make_tier(h, "anchor_reorg", _brief(reorgs[0], day))
            if out:
                return out

    # 二板
    if 2 in by_h and not layer_all_gonggao(by_h[2], day):
        layer = by_h[2]
        nats = [s for s in layer if is_natural(s, day)]
        base = nats if nats else layer
        base = sorted(base, key=lambda s: -(amount_yi(s) or 0))
        out = make_tier(2, "anchor_two", _brief(base[0], day))
        if out:
            return out

    for h in heights:
        if layer_all_gonggao(by_h[h], day):
            continue
        layer = sorted(by_h[h], key=lambda s: -(amount_yi(s) or 0))
        out = make_tier(h, "fallback", _brief(layer[0], day))
        if out:
            return out
    return empty


def fmt_tier(tier: list[dict], limit: int = 10) -> str:
    parts = []
    for x in tier[:limit]:
        a = f"{x['amount_yi']}亿" if x["amount_yi"] is not None else "?"
        tags = []
        if x["is_yizi"]:
            tags.append("一字")
        if x["is_gonggao"]:
            tags.append("公告")
        t = f"[{'+'.join(tags)}]" if tags else ""
        parts.append(f"{x['name']}/{a}{t}")
    more = f" …+{len(tier) - limit}" if len(tier) > limit else ""
    return " ".join(parts) + more


def future_nat_highs(days, pools, start_idx: int, horizon: int = 10):
    out = []
    for j in range(start_idx, min(start_idx + horizon, len(days))):
        d = days[j]
        mx, highs = natural_max(pools[d], d)
        if mx <= 0:
            continue
        out.append((d, mx, highs))
    return out


def hit_members(members: set[str], fut):
    if not members:
        return False, None
    for day, mx, highs in fut:
        inter = {s["code"] for s in highs} & members
        if inter:
            names = [s["name"] for s in highs if s["code"] in inter]
            return True, (day, mx, names)
    return False, None


def main() -> int:
    days, pools, pools_m = load_days()

    print("=== 盈新发展 连板粘性公告 ===")
    for d in ("2025-10-24", "2025-10-27", "2025-10-28", "2025-10-29"):
        if d not in pools:
            continue
        for s in pools[d]:
            if s["name"] == "盈新发展":
                print(
                    d,
                    s["boards"],
                    "theme=",
                    s.get("theme"),
                    "当日主属性公告=",
                    is_gonggao_raw(s),
                    "粘性公告=",
                    is_gonggao(s, d),
                    "自然=",
                    is_natural(s, d),
                )

    print("\n=== 个案 锚点→整层梯队 ===")
    for d in ("2026-01-21", "2026-01-22", "2025-10-28", "2025-10-29"):
        if d not in pools:
            continue
        mx, highs = natural_max(pools[d], d)
        print(
            f"\n{d} 自然高标={mx}板",
            [h["name"] for h in highs[:5]],
        )
        lad = pick_ladder(pools[d], d)
        an = lad["anchor"]
        print(
            f"  锚点={an['name'] if an else None}({lad['anchor_type']}) "
            f"→ 梯队={lad['height']}板 n={len(lad['members'])}"
        )
        print("  层内", fmt_tier(lad["tier"]))

    results = []
    for i in range(1, len(days)):
        prev, cur = days[i - 1], days[i]
        dead_ok, mx, dead, alive = is_high_tier_dead(
            pools[prev], set(pools_m[cur].keys()), prev
        )
        if not dead_ok:
            continue
        broken = [h for h in dead if is_natural(h, prev)]
        if not broken:
            broken = dead
        lad = pick_ladder(pools[cur], cur)
        ti = days.index(cur)
        fut = future_nat_highs(days, pools, ti + 1, 10) if ti + 1 < len(days) else []
        ha, ev = hit_members(lad["members"], fut)
        results.append(
            {
                "T": cur,
                "broken": broken,
                "tier_height": mx,
                "tier_dead": dead,
                "ladder": lad,
                "hit_any": ha,
                "ev": ev,
            }
        )

    n = len(results)
    print("\n=== 节点统计 ===")
    print(f"节点 {n}")
    if not n:
        return 0
    ha = sum(r["hit_any"] for r in results)
    print(f"T+1~10 自然高标∈梯队整层: {ha}/{n} = {ha/n:.1%}")

    by = defaultdict(list)
    for r in results:
        by[r["ladder"]["anchor_type"]].append(r)
    for rule, grp in sorted(by.items(), key=lambda x: -len(x[1])):
        h = sum(x["hit_any"] for x in grp) / len(grp)
        avg = sum(len(x["ladder"]["members"]) for x in grp) / len(grp)
        print(f"  {rule}: n={len(grp)} hit={h:.1%} 均层人数={avg:.1f}")

    print("\n=== 白银+盈方微同层节点 ===")
    for r in results:
        m = r["ladder"]["members"]
        if "601212" in m and "000670" in m:
            print(r["T"], r["ladder"]["detail"], "hit", r["hit_any"], r["ev"])

    print("\n--- 最近 6 节点 ---")
    for r in results[-6:]:
        dead = "、".join(f"{x['name']}{x['boards']}" for x in r["broken"][:4])
        lad = r["ladder"]
        an = lad["anchor"]
        print(
            f"{r['T']} 死绝{r.get('tier_height')}板层({dead}) "
            f"锚点={an['name'] if an else '-'} → {lad['height']}板 "
            f"n={len(lad['members'])} hit={r['hit_any']}"
        )
        print(" ", fmt_tier(lad["tier"], 8))

    # 自检：远大断而大有续 的那天不应出节点
    print("\n=== 自检 2025-10-21 是否误出节点 ===")
    has_1021 = any(r["T"] == "2025-10-21" for r in results)
    print("2025-10-21 在节点列表:", has_1021, "（应为 False）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
