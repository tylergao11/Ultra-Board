# -*- coding: utf-8 -*-
"""第二步数据底表：节点日 × 纯往下锚层票 → 真实次日开盘涨幅%。

字段：
  T, T1, code, name, boards_T, theme, amount_yi, yizi, gonggao, natural
  open_pct_T1   次日开盘涨幅%（ohlc_cache / zt_pool，真实价算）
  open_T1, prev_close_T1, high_T1, low_T1, close_T1
  cont_T1       T+1 是否连板晋级（在涨停池且 boards=T+1）
  in_zt_T1      T+1 是否在涨停池
  dead_h, dead_names, down_h, anchor_type, anchor_name

输出：
  data/kaipanla/ladder_daily/node_t1_open_pct.csv
  data/kaipanla/ladder_daily/node_t1_open_pct.json
  data/kaipanla/ladder_daily/node_t1_open_pct.md  （覆盖率摘要）
"""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "kaipanla" / "ohlc_cache"
OUT_DIR = ROOT / "data" / "kaipanla" / "ladder_daily"

_bars: dict[str, dict] = {}


def load_bars(code: str) -> dict:
    code = str(code).zfill(6)
    if code in _bars:
        return _bars[code]
    p = CACHE / f"{code}.json"
    if not p.exists():
        _bars[code] = {}
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        _bars[code] = d.get("bars") or {}
    except Exception:
        _bars[code] = {}
    return _bars[code]


def bar(code: str, day: str) -> dict | None:
    b = load_bars(code).get(day)
    return b if b else None


def open_pct_from_bar(b: dict) -> float | None:
    if b.get("open_pct") is not None:
        try:
            return round(float(b["open_pct"]), 4)
        except (TypeError, ValueError):
            pass
    try:
        o, prev = float(b["open"]), float(b["prev_close"])
        if prev > 0:
            return round((o / prev - 1.0) * 100.0, 4)
    except (TypeError, ValueError, KeyError):
        pass
    return None


def main() -> int:
    days, pools, pools_m = bt.load_days()
    rows: list[dict] = []
    miss_ohlc = 0
    n_nodes = 0

    for i in range(1, len(days) - 1):
        prev, cur = days[i - 1], days[i]
        t1 = days[i + 1]
        ok, dead_h, dead, _ = bt.is_high_tier_dead(
            pools[prev], set(pools_m[cur].keys()), prev
        )
        if not ok:
            continue
        n_nodes += 1
        lad = bt.pick_ladder(pools[cur], cur)
        if lad.get("rule") == "empty":
            continue
        members = lad.get("members") or set()
        dead_names = "、".join(f"{s['name']}{s['boards']}" for s in dead)
        an = lad.get("anchor") or {}
        anchor_name = an.get("name") or ""
        anchor_type = lad.get("anchor_type") or ""
        down_h = lad.get("height")

        for s in pools[cur]:
            if s["code"] not in members:
                continue
            code = str(s["code"]).zfill(6)
            b0 = int(s.get("boards") or 0)
            s1 = pools_m.get(t1, {}).get(code)
            in_zt = s1 is not None
            cont = bool(s1) and int(s1.get("boards") or 0) == b0 + 1

            # 次日开盘：优先 cache；其次 T+1 zt_pool 上的 open_pct
            b1 = bar(code, t1)
            op = open_pct_from_bar(b1) if b1 else None
            open_v = high_v = low_v = close_v = prev_v = None
            if b1:
                open_v = b1.get("open")
                high_v = b1.get("high")
                low_v = b1.get("low")
                close_v = b1.get("close")
                prev_v = b1.get("prev_close")
            if op is None and s1 is not None:
                op = s1.get("open_pct")
                try:
                    op = float(op) if op is not None else None
                except (TypeError, ValueError):
                    op = None
                open_v = open_v if open_v is not None else s1.get("open")
                high_v = high_v if high_v is not None else s1.get("high")
                low_v = low_v if low_v is not None else s1.get("low")
                close_v = close_v if close_v is not None else s1.get("price")
                prev_v = prev_v if prev_v is not None else s1.get("prev_close")

            if op is None:
                miss_ohlc += 1

            rows.append(
                {
                    "T": cur,
                    "T1": t1,
                    "code": code,
                    "name": s.get("name") or "",
                    "boards_T": b0,
                    "theme": s.get("theme") or "",
                    "amount_yi": bt.amount_yi(s),
                    "yizi": bt.is_yizi(s),
                    "gonggao": bt.is_gonggao(s, cur),
                    "natural": bt.is_natural(s, cur),
                    "open_pct_T1": op,
                    "open_T1": open_v,
                    "high_T1": high_v,
                    "low_T1": low_v,
                    "close_T1": close_v,
                    "prev_close_T1": prev_v,
                    "cont_T1": cont,
                    "in_zt_T1": in_zt,
                    "dead_h": dead_h,
                    "dead_names": dead_names,
                    "down_h": down_h,
                    "anchor_type": anchor_type,
                    "anchor_name": anchor_name,
                }
            )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "node_t1_open_pct.csv"
    json_path = OUT_DIR / "node_t1_open_pct.json"
    md_path = OUT_DIR / "node_t1_open_pct.md"

    if rows:
        fields = list(rows[0].keys())
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    json_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # summary
    n = len(rows)
    has = [r for r in rows if r["open_pct_T1"] is not None]
    ops = [float(r["open_pct_T1"]) for r in has]
    cont_n = sum(1 for r in rows if r["cont_T1"])
    lines = [
        "# 节点日 · 纯往下锚层 · 次日开盘涨幅（真实 OHLC）",
        "",
        f"- 节点数：**{n_nodes}**",
        f"- 票·次（纯往下锚层）：**{n}**",
        f"- 有次日 open_pct：**{len(has)}** ({len(has)/n:.1%})" if n else "",
        f"- 缺 OHLC：**{miss_ohlc}**",
        f"- 次日连板晋级：**{cont_n}/{n}** = {cont_n/n:.1%}" if n else "",
        "",
    ]
    if ops:
        ops_s = sorted(ops)
        def pct(p):
            return ops_s[int(round((len(ops_s) - 1) * p))]
        mean = sum(ops) / len(ops)
        lines += [
            "## 次日开盘涨幅% 分布（有数据样本）",
            "",
            f"| 指标 | 值 |",
            f"|------|-----|",
            f"| 均值 | {mean:.2f}% |",
            f"| 中位 | {pct(0.5):.2f}% |",
            f"| p25 | {pct(0.25):.2f}% |",
            f"| p75 | {pct(0.75):.2f}% |",
            f"| ≥5% | {sum(1 for x in ops if x>=5)/len(ops):.1%} |",
            f"| ≥9% | {sum(1 for x in ops if x>=9)/len(ops):.1%} |",
            f"| <0% | {sum(1 for x in ops if x<0)/len(ops):.1%} |",
            "",
            "## 按是否次日连板",
            "",
        ]
        for flag, lab in ((True, "连板"), (False, "未连板")):
            sub = [float(r["open_pct_T1"]) for r in has if r["cont_T1"] is flag]
            if sub:
                lines.append(
                    f"- **{lab}** n={len(sub)} 开盘均值 {sum(sub)/len(sub):.2f}% "
                    f"中位 {sorted(sub)[len(sub)//2]:.2f}%"
                )
        lines += [
            "",
            f"文件：",
            f"- `{csv_path.relative_to(ROOT)}`",
            f"- `{json_path.relative_to(ROOT)}`",
            "",
            "口径：节点日 = 自然高死绝；锚层 = **纯往下 pick_ladder**；"
            "`open_pct_T1` = T+1 开盘相对 T 收盘（cache 优先）。",
            "",
            "第二步可在此表上做定票/分层，不再缺次日开盘。",
        ]

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nrows={n} nodes={n_nodes}")
    # sample
    for r in rows[:3]:
        print(
            r["T"],
            r["name"],
            r["boards_T"],
            "open_pct_T1=",
            r["open_pct_T1"],
            "cont=",
            r["cont_T1"],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
