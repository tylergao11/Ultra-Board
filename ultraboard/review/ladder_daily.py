# -*- coding: utf-8 -*-
"""涨停梯队逐日变化（高度梯队 + 昨→今变化）。

组织轴 = 连板高度与日间变化。theme 只取开盘啦梯队列表字段，禁止读取个股详情
属性或 concepts 概念堆。公告／自然身份只看最高板日 theme；断板时看前一交易日。

产物 data/kaipanla/ladder_daily/：
  by_day/YYYY-MM-DD.md|.json
  index.md / index.json / README.md

安全日文件严格截断在各自日期；完整后续路径只写入隐藏隔离区。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from ultraboard.kaipanla.announcements import (
    is_announcement_theme,
    resolve_identity,
)
from ultraboard.kaipanla.price_shapes import is_one_price

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "kaipanla" / "raw"
OUT_DIR = ROOT / "data" / "kaipanla" / "ladder_daily"

def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def list_trading_days(raw_dir: Path = RAW_DIR) -> list[str]:
    days = []
    if not raw_dir.is_dir():
        return days
    for p in raw_dir.iterdir():
        if p.is_dir() and (p / "zt_pool.json").exists():
            days.append(p.name)
    return sorted(days)


def is_gonggao_theme(theme: str) -> bool:
    return is_announcement_theme(theme)


def format_theme(theme: str, *, announcement: bool | None = None) -> str:
    """梯队 theme 展示；个股应显式传入同日公告身份。"""
    t = (theme or "").strip() or "（无）"
    if announcement is None:
        announcement = is_gonggao_theme(t)
    if announcement:
        return f"{t}[公告板]"
    return t


def is_yizi_board(s: dict) -> bool:
    """真一字只认同一价格口径的开盘价=最高价=最低价。"""
    return is_one_price(s)


def _amount_from_stock(s: dict) -> float | None:
    """当日成交额（元）。优先已解析字段，否则 raw[11]（DailyLimitPerformance）。"""
    for key in ("amount", "成交额"):
        if key in s and s[key] is not None:
            try:
                return float(s[key])
            except (TypeError, ValueError):
                pass
    raw = s.get("raw")
    if isinstance(raw, list) and len(raw) > 11:
        try:
            return float(raw[11])
        except (TypeError, ValueError):
            return None
    return None


def _fmt_amount_yi(amount: float | None) -> str:
    if amount is None:
        return ""
    return f"额={amount / 1e8:.2f}亿"


def _stock_brief(
    s: dict,
    *,
    day: str,
) -> dict[str, Any]:
    theme = s.get("theme") or ""
    identity = resolve_identity(
        day=day,
        theme=theme,
        sector_code=s.get("sector_code"),
    )
    gonggao = bool(identity["is_announcement"])
    effective_theme = str(identity.get("effective_theme") or theme)
    raw = s.get("raw") if isinstance(s.get("raw"), list) else None
    brief = {
        "code": s["code"],
        "name": s["name"],
        "boards": s["boards"],
        "boards_desc": s.get("boards_desc") or "",
        "theme": theme,  # 开盘啦梯队列表 theme 原文
        "effective_theme": effective_theme,
        "natural_theme": identity.get("natural_theme"),
        "natural_theme_date": identity.get("natural_theme_date"),
        "theme_display": format_theme(effective_theme, announcement=gonggao),
        "is_gonggao": gonggao,
        "announcement_type": identity["announcement_type"],
        "announcement_origin_date": identity["announcement_origin_date"],
        "announcement_source": identity["announcement_source"],
        "sector_code": s.get("sector_code") or "",
        "is_fanbao": bool(s.get("is_fanbao")),
        "first_limit_ts": s.get("first_limit_ts"),
        "open": s.get("open"),
        "high": s.get("high"),
        "low": s.get("low"),
        "price": s.get("price"),
        "prev_close": s.get("prev_close"),
        "open_pct": s.get("open_pct"),
        "raw": raw,
    }
    brief["is_yizi"] = is_yizi_board(brief)
    # 仅公告板挂成交额（材料只展示这类）
    if gonggao:
        brief["amount"] = _amount_from_stock(s)
    # raw 仅用于判定，不进派生 json（体量大）
    brief.pop("raw", None)
    return brief


def _pool_map(
    zt: dict,
    *,
    day: str,
) -> dict[str, dict]:
    return {
        s["code"]: _stock_brief(
            s,
            day=day,
        )
        for s in zt.get("stocks") or []
    }


def is_first_board_layer(s: dict) -> bool:
    """日内首板层：普通首板 + 反包板（反包也是日内首板，计入发酵）。"""
    if bool(s.get("is_fanbao")):
        return True
    return int(s.get("boards") or 0) == 1


def _theme_first_board_counts(pool: dict[str, dict]) -> dict[str, int]:
    """按首板当日 theme 统计市场宽度；不改变任何股票的同日身份。"""
    counts: dict[str, int] = defaultdict(int)
    for s in pool.values():
        if not is_first_board_layer(s) or s.get("is_gonggao"):
            continue
        th = s.get("theme") or "（无）"
        counts[th] += 1
    return dict(sorted(counts.items(), key=lambda x: (-x[1], x[0])))


def _ladder_ge2(
    pool: dict[str, dict],
    theme_fb: dict[str, int],
) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for s in pool.values():
        if int(s["boards"]) < 2:
            continue
        item = dict(s)
        th = item.get("effective_theme") or item.get("theme") or "（无）"
        item["theme_first_board_count"] = int(theme_fb.get(th, 0))
        buckets[str(s["boards"])].append(item)
    for k in buckets:
        buckets[k].sort(key=lambda x: (x["code"],))
    return {k: buckets[k] for k in sorted(buckets.keys(), key=int, reverse=True)}


def _filter_ge2(items: list[dict], key: str = "boards") -> list[dict]:
    return [x for x in items if int(x.get(key) or 0) >= 2]


def _diff_days(
    prev_date: str | None,
    prev_pool: dict[str, dict] | None,
    cur_date: str,
    cur_pool: dict[str, dict],
    prev_board_counts: dict | None,
    cur_board_counts: dict,
) -> dict[str, Any]:
    if not prev_date or prev_pool is None:
        new_ge2 = [dict(s) for s in cur_pool.values() if int(s["boards"]) >= 2]
        new_ge2.sort(key=lambda x: (-x["boards"], x["code"]))
        return {
            "prev_date": None,
            "promoted": [],
            "continued": [],
            "new_limit": new_ge2,
            "broken": [],
            "board_counts_prev": None,
            "board_counts_cur": cur_board_counts,
            "first_board_count_cur": sum(1 for s in cur_pool.values() if int(s["boards"]) == 1),
        }

    promoted, continued, new_limit = [], [], []
    for code, cur in cur_pool.items():
        if int(cur["boards"]) < 2:
            continue
        if code not in prev_pool:
            new_limit.append(dict(cur))
            continue
        prev = prev_pool[code]
        item = {
            **cur,
            "prev_boards": prev["boards"],
            "prev_theme": prev.get("theme") or "",
        }
        if cur["boards"] > prev["boards"]:
            promoted.append(item)
        else:
            continued.append(item)

    broken = []
    for code, prev in prev_pool.items():
        if code in cur_pool:
            continue
        if int(prev["boards"]) < 2:
            continue
        broken.append({
            **prev,
            "last_limit_date": prev_date,
            "break_date": cur_date,
            "boards_before_break": prev["boards"],
        })

    promoted.sort(key=lambda x: (-x["boards"], x["code"]))
    continued.sort(key=lambda x: (-x["boards"], x["code"]))
    new_limit.sort(key=lambda x: (-x["boards"], x["code"]))
    broken.sort(key=lambda x: (-x["boards_before_break"], x["code"]))

    return {
        "prev_date": prev_date,
        "promoted": promoted,
        "continued": continued,
        "new_limit": new_limit,
        "broken": broken,
        "board_counts_prev": prev_board_counts,
        "board_counts_cur": cur_board_counts,
        "first_board_count_cur": sum(1 for s in cur_pool.values() if int(s["boards"]) == 1),
    }


def _dist(counts: dict | None) -> str:
    if not counts:
        return "-"
    parts = []
    for k in sorted(counts.keys(), key=lambda x: int(x), reverse=True):
        if str(k) == "1":
            continue
        parts.append(f"{k}×{counts[k]}")
    return " ".join(parts) if parts else "-"


def _gonggao_amount_suffix(s: dict) -> str:
    """仅公告板附加 额=x.xx亿。"""
    if not s.get("is_gonggao"):
        return ""
    amt = s.get("amount")
    if amt is None:
        amt = _amount_from_stock(s)
    part = _fmt_amount_yi(amt)
    return f" {part}" if part else ""


def _theme_fb_suffix(s: dict) -> str:
    """非公告板：挂梯队 theme 对应首板发酵数（含反包板）。"""
    if s.get("is_gonggao"):
        return ""
    n = s.get("theme_first_board_count")
    if n is None:
        return ""
    return f" 首板×{int(n)}"


def _open_pct_suffix(s: dict) -> str:
    """开盘涨幅%：仅 ≥2 板展示；首板不需要开盘价。"""
    boards = s.get("boards")
    if boards is None:
        boards = s.get("boards_before_break")
    try:
        if boards is not None and int(boards) < 2:
            return ""
    except (TypeError, ValueError):
        pass
    op = s.get("open_pct")
    if op is None:
        return ""
    try:
        return f" 开盘%={float(op):+.2f}"
    except (TypeError, ValueError):
        return ""


def _stock_attrs_suffix(s: dict) -> str:
    """开盘% + 公告板额 / 非公告板首板发酵。"""
    return _open_pct_suffix(s) + _gonggao_amount_suffix(s) + _theme_fb_suffix(s)


def _yizi_tag(s: dict) -> str:
    return "[一字]" if is_yizi_board(s) else ""


def _stock_token(s: dict, *, boards: int | None = None) -> str:
    th = format_theme(
        s.get("theme") or "",
        announcement=bool(s.get("is_gonggao")),
    )
    return f"{s['name']}({s['code']}){_yizi_tag(s)} theme={th}{_stock_attrs_suffix(s)}"


def _change_token(s: dict, kind: str) -> str:
    th = format_theme(
        s.get("theme") or "",
        announcement=bool(s.get("is_gonggao")),
    )
    suf = _stock_attrs_suffix(s)
    yz = _yizi_tag(s)
    if kind == "promoted":
        return f"{s['name']}({s['code']}){yz} {s.get('prev_boards')}→{s['boards']} theme={th}{suf}"
    if kind == "broken":
        return f"{s['name']}({s['code']}){yz} 断前{s.get('boards_before_break')} theme={th}{suf}"
    if kind == "new":
        return f"{s['name']}({s['code']}){yz} {s['boards']}板 theme={th}{suf}"
    if kind == "continued":
        return f"{s['name']}({s['code']}){yz} {s['boards']}板 theme={th}{suf}"
    return _stock_token(s)


def _first_board_line(theme_fb: dict[str, int], total: int) -> str:
    if total <= 0:
        return "首板发酵=0（含反包）"
    parts = []
    for th, n in list(theme_fb.items())[:15]:
        parts.append(f"{format_theme(th)}×{n}")
    more = f" …+{len(theme_fb) - 15}" if len(theme_fb) > 15 else ""
    return f"首板发酵={total}（含反包） [" + " ".join(parts) + more + "]"


def day_to_markdown(doc: dict) -> str:
    """高度梯队 + 变化；短字段，无说明书。"""
    d = doc["date"]
    m = doc["market"]
    ch = doc["change"]
    prev = ch.get("prev_date") or "-"
    n1 = int(m.get("first_board_count") or 0)
    n_ge2 = int(m.get("ge2_count") or 0)
    theme_fb = m.get("theme_first_board_counts") or {}

    lines = [
        f"# {d}  昨={prev}",
        f"meta: 涨停={m['count']}  ≥2={n_ge2}  首板={n1}  最高={m['max_board']}",
        f"dist昨: {_dist(ch.get('board_counts_prev'))}",
        f"dist今: {_dist(ch.get('board_counts_cur') or m.get('board_counts'))}",
        _first_board_line(theme_fb, n1),
        "",
        "## 今梯队(≥2 高度↓)",
    ]

    ladder = doc.get("ladder") or {}
    if not ladder:
        lines.append("(无)")
    else:
        for h, stocks in ladder.items():
            if str(h) == "1":
                continue
            # 同行多只：高度 | 票1; 票2
            toks = [_stock_token(s) for s in stocks]
            lines.append(f"{h} | " + " ; ".join(toks))

    lines.append("")
    lines.append("## 变化(相对昨 ≥2)")

    promoted = ch.get("promoted") or []
    continued = ch.get("continued") or []
    new_limit = ch.get("new_limit") or []
    broken = ch.get("broken") or []

    if promoted:
        lines.append("晋级: " + " ; ".join(_change_token(s, "promoted") for s in promoted))
    if broken:
        lines.append("断板: " + " ; ".join(_change_token(s, "broken") for s in broken))
    if new_limit:
        lines.append("新上: " + " ; ".join(_change_token(s, "new") for s in new_limit))
    if continued:
        # 续板多时只写数量+≥3明细，避免刷屏
        high = [s for s in continued if int(s["boards"]) >= 3]
        if high:
            lines.append(
                f"续板: n={len(continued)} ≥3: "
                + " ; ".join(_change_token(s, "continued") for s in high)
            )
        else:
            lines.append(f"续板: n={len(continued)}")
    if not (promoted or broken or new_limit or continued):
        if prev == "-":
            lines.append("(首日无对比)")
        else:
            lines.append("(无≥2变化)")

    # 本日触及的跟随链：反包日 or 反包后再连板日
    follow_hits = doc.get("follow_chain_hits") or []
    if follow_hits:
        lines.append("")
        lines.append("## 跟随(断→反包→再连板…)")
        for e in follow_hits:
            lines.append(_format_follow_hit_line(e, d))

    lines.append("")
    return "\n".join(lines) + "\n"


def _identity_labels(s: dict) -> list[str]:
    labels = []
    if int(s.get("boards") or 0) <= 1:
        labels.append("首板")
    if s.get("is_fanbao"):
        labels.append("反包板")
    if not labels:
        labels.append(f"{s.get('boards')}板")
    return labels


def _anchor_brief(anchor: dict | None) -> dict | None:
    if not anchor:
        return None
    return {
        "code": anchor["code"],
        "name": anchor["name"],
        "boards": anchor["boards"],
        "theme": anchor.get("theme") or "",
        "theme_display": format_theme(anchor.get("theme") or ""),
    }


def _resolve_follow_anchor(
    pool: dict[str, dict],
    code: str,
    theme_hint: str,
) -> tuple[dict | None, str]:
    """同 theme 的≥2高标。优先当前 theme，再试 theme_hint。"""
    self = pool.get(code) or {}
    theme_now = self.get("theme") or theme_hint or ""

    def peers(theme: str) -> list[dict]:
        return [
            p for p in pool.values()
            if p["code"] != code
            and (p.get("theme") or "") == theme
            and int(p["boards"]) >= 2
        ]

    cands = peers(theme_now)
    src = "same_theme"
    if not cands and theme_hint and theme_hint != theme_now:
        cands = peers(theme_hint)
        src = "theme_hint"
    cands.sort(key=lambda x: (-x["boards"], x["code"]))
    return (cands[0] if cands else None), src


def _follow_step(
    day: str,
    role: str,
    pool: dict[str, dict],
    code: str,
    theme_hint: str,
) -> dict[str, Any]:
    s = pool[code]
    theme = s.get("effective_theme") or s.get("theme") or theme_hint or ""
    anchor, src = _resolve_follow_anchor(pool, code, theme_hint)
    height = int(anchor["boards"]) if anchor else None
    theme_fb = _theme_first_board_counts(pool)
    fb_n = int(theme_fb.get(theme, 0))
    identity = _identity_labels(s)
    yizi = is_yizi_board(s)
    if yizi and "一字" not in identity:
        identity = ["一字"] + identity
    return {
        "date": day,
        "role": role,  # fanbao | continue
        "self_boards": s["boards"],
        "is_fanbao": bool(s.get("is_fanbao")),
        "is_yizi": yizi,
        "is_gonggao": bool(s.get("is_gonggao")),
        "identity": identity,
        "identity_text": "+".join(identity),
        "theme": theme,
        "theme_display": format_theme(
            theme,
            announcement=bool(s.get("is_gonggao")),
        ),
        "follow_anchor": _anchor_brief(anchor),
        "follow_ladder_height": height,
        "follow_ladder_label": f"{height}板梯队" if height else None,
        "theme_first_board_count": fb_n,
        "peer_source": src,
        "amount": s.get("amount") if s.get("is_gonggao") else None,
    }


def _path_text(steps: list[dict], boards_before: int) -> str:
    """2板→断→反包跟4板→次日2板跟5板…"""
    parts = [f"{boards_before}板→断"]
    for i, st in enumerate(steps):
        lab = st.get("follow_ladder_label")
        follow_bit = f"跟{lab}" if lab else "无跟随高标"
        if st.get("role") == "fanbao":
            parts.append(f"反包(自身{st['self_boards']}板){follow_bit}")
        else:
            tag = "次日" if i == 1 else f"D+{i}"
            parts.append(f"{tag}(自身{st['self_boards']}板){follow_bit}")
    return "→".join(parts)


def build_fanbao_follow_events(
    days: list[str],
    pools: dict[str, dict[str, dict]],
) -> list[dict[str, Any]]:
    """≥2→断板→反包，并沿之后连续在池日续记跟随高度。

    例：反包日跟4板梯队，次日又连板跟5板梯队。
    """
    events: list[dict[str, Any]] = []
    day_index = {d: i for i, d in enumerate(days)}

    for i in range(len(days) - 2):
        d_last, d_break, d_fb = days[i], days[i + 1], days[i + 2]
        p_last, p_break, p_fb = pools[d_last], pools[d_break], pools[d_fb]

        for code, s_last in p_last.items():
            if int(s_last["boards"]) < 2:
                continue
            if code in p_break or code not in p_fb:
                continue
            s_fb = p_fb[code]
            if not (s_fb.get("is_fanbao") or int(s_fb["boards"]) == 1):
                continue

            theme_before = s_last.get("effective_theme") or s_last.get("theme") or ""
            steps: list[dict] = [
                _follow_step(d_fb, "fanbao", p_fb, code, theme_before)
            ]

            # 反包后每个仍在涨停池的交易日：再连板，跟随高度可升（4→5…）
            j = day_index[d_fb] + 1
            while j < len(days):
                d = days[j]
                pool = pools[d]
                if code not in pool:
                    break
                steps.append(
                    _follow_step(d, "continue", pool, code, theme_before)
                )
                j += 1

            first = steps[0]
            last = steps[-1]
            gonggao = bool(first.get("is_gonggao"))
            amount = None
            if gonggao:
                amount = steps[0].get("amount")
                if amount is None:
                    amount = s_last.get("amount")

            events.append({
                "code": code,
                "name": s_last["name"],
                "last_limit_date": d_last,
                "break_date": d_break,
                "fanbao_date": d_fb,
                "end_date": last["date"],
                "boards_before_break": s_last["boards"],
                "theme_before_break": theme_before,
                "theme_before_display": format_theme(
                    theme_before,
                    announcement=bool(s_last.get("is_gonggao")),
                ),
                "is_gonggao": gonggao,
                "amount": amount,
                "self_on_fanbao_day": {
                    "boards": first["self_boards"],
                    "theme": first["theme"],
                    "theme_display": first["theme_display"],
                    "is_fanbao": first["is_fanbao"],
                    "identity": first["identity"],
                    "identity_text": first["identity_text"],
                },
                # 反包日快照（兼容）
                "follow_anchor": first.get("follow_anchor"),
                "follow_ladder_height": first.get("follow_ladder_height"),
                "follow_ladder_label": first.get("follow_ladder_label"),
                "theme_first_board_count_on_fanbao": first.get("theme_first_board_count"),
                "peer_source": first.get("peer_source"),
                # 全路径：反包日 + 之后再连板日
                "follow_path": steps,
                "follow_path_text": _path_text(steps, s_last["boards"]),
                "dates_on_path": [st["date"] for st in steps],
            })

    events.sort(key=lambda e: (e["fanbao_date"], -e["boards_before_break"], e["code"]))
    return events


def _follow_event_as_of(event: dict[str, Any], cutoff: str) -> dict[str, Any]:
    """生成严格截至 cutoff 的公开快照，不携带后续路径。"""
    steps = [step for step in event.get("follow_path") or [] if step["date"] <= cutoff]
    if not steps:
        raise ValueError(f"跟随事件在信息截止日前没有可见步骤: {cutoff}")
    snapshot = dict(event)
    snapshot.pop("end_date", None)
    snapshot["information_cutoff"] = cutoff
    snapshot["observed_through"] = steps[-1]["date"]
    snapshot["follow_path"] = steps
    snapshot["follow_path_text"] = _path_text(steps, event["boards_before_break"])
    snapshot["dates_on_path"] = [step["date"] for step in steps]
    return snapshot


def _format_follow_hit_line(e: dict, day: str) -> str:
    steps = e.get("follow_path") or []
    today = next((st for st in steps if st["date"] == day), None)
    th = format_theme(
        (today or {}).get("theme")
        or e.get("theme_before_break")
        or "",
        announcement=bool((today or {}).get("is_gonggao")),
    )
    if today and today.get("follow_ladder_label") and today.get("follow_anchor"):
        a = today["follow_anchor"]
        follow = (
            f"{a['name']}({a['code']}){a['boards']}板→{today['follow_ladder_label']}"
        )
    else:
        follow = (today or {}).get("follow_ladder_label") or "无同theme≥2高标"

    role = "反包日" if (today or {}).get("role") == "fanbao" else "再连板"
    self_b = (today or {}).get("self_boards", "?")
    ident = (today or {}).get("identity_text") or ""
    amt = ""
    if e.get("is_gonggao") and e.get("amount") is not None:
        amt = f" | {_fmt_amount_yi(e['amount'])}"
    fb_n = (today or {}).get("theme_first_board_count", 0)
    path = e.get("follow_path_text") or ""
    yz = "[一字]" if (today or {}).get("is_yizi") else ""
    return (
        f"{e['name']}({e['code']}){yz}: 断前{e['boards_before_break']} | "
        f"今日={role}/自身{self_b}板/{ident} | theme={th}{amt} | "
        f"跟={follow} | 首板×{fb_n} | 路径:{path}"
    )


def build_one_day(
    day: str,
    prev_date: str | None,
    prev_pool: dict[str, dict] | None,
    prev_board_counts: dict | None,
    raw_dir: Path = RAW_DIR,
) -> tuple[dict, dict[str, dict], dict]:
    zt = _read_json(raw_dir / day / "zt_pool.json")
    pool = _pool_map(
        zt,
        day=day,
    )

    board_counts = zt.get("board_counts") or {}
    if not board_counts:
        board_counts = {}
        for s in pool.values():
            k = str(s["boards"])
            board_counts[k] = board_counts.get(k, 0) + 1

    theme_fb = _theme_first_board_counts(pool)
    # 首板发酵：boards==1 或 is_fanbao（反包计入）
    first_board_count = sum(1 for s in pool.values() if is_first_board_layer(s))
    ge2_count = sum(1 for s in pool.values() if int(s["boards"]) >= 2)

    change = _diff_days(
        prev_date, prev_pool, day, pool, prev_board_counts, board_counts
    )
    # 变化名单挂上当日 theme 首板发酵数（非公告板展示用）
    for key in ("promoted", "continued", "new_limit", "broken"):
        for item in change.get(key) or []:
            th = item.get("effective_theme") or item.get("theme") or "（无）"
            item["theme_first_board_count"] = int(theme_fb.get(th, 0))

    doc = {
        "date": day,
        "market": {
            "sjzt": zt.get("sjzt"),
            "count": zt.get("count", len(pool)),
            "max_board": zt.get("max_board")
            or max((s["boards"] for s in pool.values()), default=0),
            "board_counts": board_counts,
            "first_board_count": first_board_count,
            "ge2_count": ge2_count,
            "theme_first_board_counts": theme_fb,
            "theme_field": "开盘啦梯队列表 theme（公告身份看最高板日）",
            "first_board_note": "含反包板（日内首板层）",
            "announcement_taxonomy": (
                "data/kaipanla/announcement_taxonomy.json"
            ),
            "fanbao_count": zt.get(
                "fanbao_count", sum(1 for s in pool.values() if s["is_fanbao"])
            ),
        },
        "ladder": _ladder_ge2(pool, theme_fb),
        "change": change,
        "source": {
            "zt_pool": f"data/kaipanla/raw/{day}/zt_pool.json",
        },
    }
    return doc, pool, board_counts


def build_ladder_daily(
    raw_dir: Path = RAW_DIR,
    out_dir: Path = OUT_DIR,
) -> dict[str, Any]:
    days = list_trading_days(raw_dir)
    by_day_dir = out_dir / "by_day"
    by_day_dir.mkdir(parents=True, exist_ok=True)
    for old in by_day_dir.glob("*"):
        if old.is_file():
            old.unlink()

    index_days = []
    day_docs: dict[str, dict] = {}
    pools: dict[str, dict[str, dict]] = {}
    total_broken = 0

    prev_date = None
    prev_pool = None
    prev_board_counts = None
    for day in days:
        doc, pool, board_counts = build_one_day(
            day,
            prev_date,
            prev_pool,
            prev_board_counts,
            raw_dir=raw_dir,
        )
        day_docs[day] = doc
        pools[day] = pool
        n_broken = len(doc["change"].get("broken") or [])
        total_broken += n_broken
        index_days.append({
            "date": day,
            "count": doc["market"]["count"],
            "ge2": doc["market"]["ge2_count"],
            "first_board": doc["market"]["first_board_count"],
            "max_board": doc["market"]["max_board"],
            "promoted": len(doc["change"].get("promoted") or []),
            "new_limit": len(doc["change"].get("new_limit") or []),
            "broken": n_broken,
            "md": f"by_day/{day}.md",
        })
        prev_date = day
        prev_pool = pool
        prev_board_counts = board_counts

    fb_events = build_fanbao_follow_events(days, pools)
    # 每个交易日：挂上「路径经过该日」的跟随链（反包日或再连板日）
    hits_by_date: dict[str, list[dict]] = defaultdict(list)
    for e in fb_events:
        for d in e.get("dates_on_path") or []:
            hits_by_date[d].append(e)

    for day, doc in day_docs.items():
        hits = [_follow_event_as_of(event, day) for event in hits_by_date.get(day, [])]
        doc["information_cutoff"] = day
        doc["fanbao_follow_events"] = [
            e for e in hits if e.get("fanbao_date") == day
        ]
        doc["follow_chain_hits"] = hits
        _write_json(by_day_dir / f"{day}.json", doc)
        _write_text(by_day_dir / f"{day}.md", day_to_markdown(doc))

    summary = {
        "day_count": len(days),
        "first_date": days[0] if days else None,
        "last_date": days[-1] if days else None,
        "total_break_ge2": total_broken,
        "fanbao_follow_events": len(fb_events),
        "announcement_taxonomy": "data/kaipanla/announcement_taxonomy.json",
        "days": index_days,
    }
    _write_json(out_dir / "index.json", summary)

    idx = [
        f"# 梯队逐日  {days[0] if days else '-'}→{days[-1] if days else '-'}  n={len(days)}",
        f"断板(≥2)={total_broken}  反包跟随={len(fb_events)}  "
        "公告分类=data/kaipanla/announcement_taxonomy.json",
        "打开 by_day/日期.md 看：今梯队 + 变化",
        "",
        "date | 涨停 | ≥2 | 首板 | 最高 | 晋级 | 断板 | 文件",
    ]
    for r in index_days:
        idx.append(
            f"{r['date']} | {r['count']} | {r['ge2']} | {r['first_board']} | "
            f"{r['max_board']} | {r['promoted']} | {r['broken']} | {r['md']}"
        )
    idx.append("")
    _write_text(out_dir / "index.md", "\n".join(idx))

    readme = """# 涨停梯队逐日变化

```bash
python -m ultraboard.review.ladder_daily
```

## 日文件结构（by_day/YYYY-MM-DD.md）

1. meta / dist昨 / dist今 / 首板数量
2. **今梯队(≥2 高度↓)** ← 主视图
3. **变化(相对昨)** 晋级 / 断板 / 新上 / 续板
4. 截至本日已经发生的反包跟随（有则）

组织轴是高度与变化，不是题材分堆。
theme=开盘啦梯队列表字段。自然票从二板起保留沿途 theme；公告身份只看最高板日
theme，断板时看断板前一交易日，不继承更早身份。公告型 theme 统一读取
`announcement_taxonomy.json`，包括 ST摘帽、举牌、定期报告、订单、再融资、
重组等。节点日前一交易日最高自然梯队断板才触发节点；若该票前一日 theme 为
公告，则其断板不触发自然节点。
`concepts` / `raw[12]` 是静态概念堆，不得用于题材关系、高低位映射或发酵匹配。
当日公告票另附 额=x.xx亿（raw[11]），且不计入当日自然题材发酵；自然票附
首板×N=按首板当日原始 theme 统计的市场宽度（含反包板），只作市场证据，
不改变个股的梯队 theme。
日文件中的跟随链严格截断在该日；完整后续路径只保存在隐藏隔离区，盲测禁止访问。
真一字：同一价格口径下开盘价=最高价=最低价 → 票名后标 [一字]。
不列首板个股名单。

## 顶层文件契约

- `by_day/`、`index.json`、`index.md`：由本命令生成的客观派生证据，可重建。
- 人工标签和完整后续路径位于隐藏隔离区，本命令的安全日文件不读取它们。
- 临时赛马、排名、收益审计和自动选层报告不在本目录长期保存。
"""
    _write_text(out_dir / "README.md", readme)

    # 去掉旧的超大 name_index（连板材料非必需）；若存在则删除以免误导
    old_ni = out_dir / "name_index.json"
    if old_ni.exists():
        old_ni.unlink()

    return {
        "day_count": len(days),
        "first_date": days[0] if days else None,
        "last_date": days[-1] if days else None,
        "total_break_events": total_broken,
        "fanbao_follow_events": len(fb_events),
        "out_dir": str(out_dir),
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    s = build_ladder_daily()
    print(
        f"ok days={s['day_count']} {s['first_date']}→{s['last_date']} "
        f"breaks={s['total_break_events']} fanbao={s['fanbao_follow_events']} "
        f"out={s['out_dir']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
