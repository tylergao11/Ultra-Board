# -*- coding: utf-8 -*-
"""开盘啦历史回灌：2025-10-01 ~ 今天。

落盘到 data/kaipanla/raw/YYYY-MM-DD/：
  sentiment.json      情绪统计（含 SJZT，用作校验基准）
  expression.json     梯队情绪指标
  zt_pool.json        完整涨停池，每只票带真实连板数
  sector_ladder.json  板块核心梯队 + 反包板标记
  _DONE               仅当校验全过才写

已验证的接口语义（勿凭猜测改动）：
  DailyLimitPerformance
    PidType 1~4 = 恰好 N 板
    PidType 5   = 「5 板及以上」，组内可能出现 6/7/8 板
    真实连板数 = 个股数组下标 15，绝不能用 PidType 顶替
    下标 18 = 描述文字，如 "7连板" / "3天2板"，仅作备注
  GetYTFP_BKHX
    历史参数是 Date（大写），不是 Day
    TD 按 TDType 分组：0=反包板 1=首板 2=2连板 … 9=打开高度标注

硬规则：
  - 不含 ST（对齐 SJZT，不含 STZT）
  - 不含北交所（920/83x 等）
  - 反包板按真实连板数归队，不抬高梯队；仅打 is_fanbao 标记
  - 涨停池总数必须等于 SJZT，少一只都不写 _DONE
  - 网络/接口失败 → 立即停；数据校验不符 → 记录并继续，收尾统一报告
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .client import KaipanlaClient, dump_json, ok

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "kaipanla"
RAW_DIR = DATA_DIR / "raw"
STATE_PATH = DATA_DIR / "backfill_state.json"
NON_TRADING_PATH = DATA_DIR / "non_trading_days.json"
MISMATCH_PATH = DATA_DIR / "mismatches.json"

START = date(2025, 10, 1)
END = date.today()

# 接口只提供 1~5；5 表示「5 板及以上」
MAX_PID = 5

REQUIRED = ("sentiment.json", "expression.json", "zt_pool.json", "sector_ladder.json", "_DONE")


def is_bse(code: str) -> bool:
    """北交所不进打板体系。"""
    c = str(code).strip()
    return c.startswith((
        "920", "430", "830", "831", "832", "833", "834", "835",
        "836", "837", "838", "839", "870", "871", "872", "873",
    ))


# --------------------------------------------------------------------------- utils

def trading_days(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def day_dir(d: date) -> Path:
    return RAW_DIR / d.isoformat()


def day_complete(d: date) -> bool:
    dd = day_dir(d)
    return all((dd / name).exists() for name in REQUIRED)


def _read_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8-sig"))
    return default


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def has_real_data(dd: Path) -> bool:
    """目录里是否已有可用数据。用于避免误删。"""
    f = dd / "sentiment.json"
    if not f.exists():
        return False
    try:
        return isinstance(_read_json(f, {}).get("info"), dict)
    except Exception:
        return False


# --------------------------------------------------------------------------- parse

def _rows(body: dict) -> list:
    info = body.get("info") or []
    if not info:
        return []
    return info[0] if isinstance(info[0], list) else []


def parse_stock(row: list, pid: int) -> tuple[dict[str, Any] | None, str | None]:
    """原始数组 → 结构化。返回 (item, error)。"""
    if not isinstance(row, list) or len(row) < 23:
        return None, f"原始行长度异常 len={len(row) if isinstance(row, list) else '非数组'}"

    code, name = str(row[0]).strip(), str(row[1]).strip()
    if not code or not name:
        return None, f"代码或名称为空: {row[:3]}"
    if is_bse(code):
        return None, None  # 北交所跳过，不算错误

    boards = row[15]
    if not isinstance(boards, int) or boards < 1:
        return None, f"{code} {name} 连板数非法: {boards!r}"

    # PidType 1~4 必须精确匹配；5 表示 5 板及以上
    if pid < MAX_PID and boards != pid:
        return None, f"{code} {name} pid={pid} 但真实连板={boards}"
    if pid == MAX_PID and boards < MAX_PID:
        return None, f"{code} {name} 落在 pid=5 组但真实连板={boards}"

    return {
        "code": code,
        "name": name,
        "boards": boards,               # 真实连板数，唯一权威
        "boards_desc": row[18] or "",   # "7连板" / "3天2板"，仅备注
        "theme": row[5] or "",
        "concepts": row[12] or "",
        "sector_code": str(row[19] or ""),
        "first_limit_ts": row[4],
        "turnover_rate": row[14],
        "price": row[21],
        "limit_pct": row[22],
        "is_fanbao": False,             # 由 sector_ladder 回填
        "raw": row,
    }, None


def parse_sector_ladder(body: dict) -> tuple[dict, set[str]]:
    """解析板块梯队，返回 (doc, 反包板代码集合)。"""
    sectors, fanbao_codes, fanbao_all = [], set(), []
    for s in body.get("List") or []:
        tiers: dict[str, list] = {}
        fanbao, height_marks = [], []
        for g in s.get("TD") or []:
            t = str(g.get("TDType"))
            for st in g.get("Stock") or []:
                code = str(st.get("StockID") or "")
                item = {"code": code, "name": st.get("StockName"), "tips": st.get("Tips") or ""}
                if t == "0":
                    if is_bse(code):
                        continue
                    fanbao.append(item)
                    fanbao_codes.add(code)
                    fanbao_all.append({**item, "sector": s.get("ZSName")})
                elif t == "9":
                    if is_bse(code):
                        continue
                    height_marks.append(item)
                else:
                    if is_bse(code):
                        continue
                    tiers.setdefault(t, []).append(item)
        sectors.append({
            "code": s.get("ZSCode"),
            "name": s.get("ZSName"),
            "count": s.get("Count"),
            "tiers": tiers,          # 键为连板高度
            "fanbao": fanbao,        # 反包板，不计入 tiers
            "height_marks": height_marks,
        })
    return {"sectors": sectors, "fanbao_all": fanbao_all}, fanbao_codes


# --------------------------------------------------------------------------- pull

def pull_pool(client: KaipanlaClient, day: str) -> tuple[list, str | None]:
    pool, seen = [], set()
    for pid in range(1, MAX_PID + 1):
        print(f"    pid={pid}/{MAX_PID} ...", flush=True)
        body = client.daily_limit_performance(day, pid)
        if not ok(body):
            return [], f"拉 pid={pid} 失败: {body.get('errmsg') or body.get('errcode')}"
        for row in _rows(body):
            item, err = parse_stock(row, pid)
            if item is None and err is None:
                continue  # 北交所
            if err:
                return [], err
            if item["code"] in seen:
                return [], f"重复代码 {item['code']}（跨 pid 出现）"
            seen.add(item["code"])
            pool.append(item)
    pool.sort(key=lambda x: (-x["boards"], x["code"]))
    return pool, None


def validate(pool: list, sentiment: dict) -> str | None:
    info = sentiment.get("info") or {}
    try:
        sjzt = int(info.get("SJZT"))
    except Exception:
        return "sentiment 缺少 SJZT"
    if len(pool) != sjzt:
        return f"涨停池 {len(pool)} 只 ≠ SJZT {sjzt}，差 {sjzt - len(pool)} 只"
    return None


def pull_one_day(
    client: KaipanlaClient,
    d: date,
    non_trading: set[str],
) -> tuple[str, str | None]:
    """返回 (status, msg)。status: ok / skip / mismatch / fail"""
    day = d.isoformat()
    dd = day_dir(d)

    sentiment = client.his_zhangfu(day)
    if not ok(sentiment):
        if str(sentiment.get("errcode")) == "1020":
            # 假期或当日未入库。只有在目录里没有可用数据时才清理，避免误删。
            if dd.exists() and not has_real_data(dd):
                for p in dd.iterdir():
                    p.unlink()
                dd.rmdir()
            if d < date.today():
                non_trading.add(day)
                _write_json(NON_TRADING_PATH, sorted(non_trading))
            return "skip", None
        return "fail", f"{day} sentiment 失败: {sentiment.get('errmsg') or sentiment.get('errcode')}"

    expression = client.zhangting_expression(day)
    if not ok(expression):
        return "fail", f"{day} expression 失败: {expression.get('errmsg') or expression.get('errcode')}"

    pool, err = pull_pool(client, day)
    if err:
        return "fail", f"{day} {err}"

    sec_body = client.sector_ladder(day)
    if not ok(sec_body):
        return "fail", f"{day} sector_ladder 失败: {sec_body.get('errmsg') or sec_body.get('errcode')}"
    sector_doc, fanbao_codes = parse_sector_ladder(sec_body)

    # 反包板只打标记，不动 boards
    for s in pool:
        if s["code"] in fanbao_codes:
            s["is_fanbao"] = True

    verr = validate(pool, sentiment)

    dd.mkdir(parents=True, exist_ok=True)
    _write_json(dd / "sentiment.json", sentiment)
    _write_json(dd / "expression.json", expression)
    _write_json(dd / "sector_ladder.json", {"date": day, **sector_doc})

    counts: dict[str, int] = {}
    for s in pool:
        counts[str(s["boards"])] = counts.get(str(s["boards"]), 0) + 1
    max_board = max((s["boards"] for s in pool), default=0)
    n_fanbao = sum(1 for s in pool if s["is_fanbao"])

    _write_json(dd / "zt_pool.json", {
        "date": day,
        "sjzt": int((sentiment.get("info") or {}).get("SJZT")),
        "count": len(pool),
        "max_board": max_board,
        "board_counts": counts,
        "fanbao_count": n_fanbao,
        "stocks": pool,
    })

    summary = (f"SJZT={len(pool)} 最高板={max_board} 反包={n_fanbao} "
               f"分布={dict(sorted(counts.items(), key=lambda x: -int(x[0])))}")
    if verr:
        (dd / "_MISMATCH").write_text(f"{verr}\n", encoding="utf-8")
        return "mismatch", f"{day} {verr}"
    if (dd / "_MISMATCH").exists():
        (dd / "_MISMATCH").unlink()
    (dd / "_DONE").write_text(f"ok {summary}\n", encoding="utf-8")
    return "ok", summary


# --------------------------------------------------------------------------- main

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    # 约 200 交易日 × 8 请求 × 0.75s ≈ 20 分钟
    client = KaipanlaClient(DATA_DIR, interval_min=0.5, interval_max=1.0)

    state = _read_json(STATE_PATH, {"completed": [], "started_at": None})
    state.setdefault("completed", [])
    if not state.get("started_at"):
        state["started_at"] = datetime.now().isoformat(timespec="seconds")

    non_trading = set(_read_json(NON_TRADING_PATH, []))
    mismatches: list[str] = list(_read_json(MISMATCH_PATH, []))

    days = trading_days(START, END)
    todo = [d for d in days if not day_complete(d) and d.isoformat() not in non_trading]

    print(f"DeviceID: {client.device_id}")
    print("间隔 0.5~1s 随机 | 不含ST | 反包不抬梯队 | 每日 8 次请求 | 目标约20分钟")
    print(f"区间 {START} ~ {END}")
    print(f"工作日 {len(days)} | 已知假期 {len(non_trading)} | 已完成 "
          f"{sum(1 for d in days if day_complete(d))} | 待拉 {len(todo)}")
    print(f"目录 {RAW_DIR}")
    print("-" * 64)

    if not todo:
        print("全部完成。")
        return 0

    for i, d in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {d.isoformat()}", flush=True)
        status, msg = pull_one_day(client, d, non_trading)

        if status == "fail":
            state["last_error"] = {"time": datetime.now().isoformat(timespec="seconds"), "msg": msg}
            _write_json(STATE_PATH, state)
            print(f"  STOP: {msg}")
            print("  修好后重跑本脚本即可续传。")
            return 1
        if status == "skip":
            print("  假期/未入库，跳过")
            continue
        if status == "mismatch":
            print(f"  !! 数量不符: {msg}（已落盘但不标完成）")
            if msg not in mismatches:
                mismatches.append(msg)
            _write_json(MISMATCH_PATH, mismatches)
            continue

        print(f"  {msg}")
        completed = set(state["completed"])
        completed.add(d.isoformat())
        state["completed"] = sorted(completed)
        state["last_ok"] = d.isoformat()
        state["last_error"] = None
        _write_json(STATE_PATH, state)

    print("-" * 64)
    if mismatches:
        print(f"完成，但有 {len(mismatches)} 天数量不符，需人工确认：")
        for m in mismatches:
            print(f"  - {m}")
    else:
        print("回灌完成，全部对齐 SJZT。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
