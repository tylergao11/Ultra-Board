# -*- coding: utf-8 -*-
"""开盘啦历史回灌：2025-10-01 ~ 今天。

落盘到 data/kaipanla/raw/YYYY-MM-DD/：
  sentiment.json      情绪统计（含 SJZT，作为跨接口范围参考）
  expression.json     梯队情绪指标
  zt_pool.json        完整涨停池，每只票带真实连板数与梯队列表 theme
  sector_ladder.json  涨停原因题材家数 + 源序 + 板块核心梯队 + 反包板标记
  _DONE               仅当校验全过才写

已验证的接口语义（勿凭猜测改动）：
  DailyLimitPerformance
    PidType 1~4 = 恰好 N 板
    PidType 5   = 「5 板及以上」，组内可能出现 6/7/8 板
    真实连板数 = 个股数组下标 15，绝不能用 PidType 顶替
    下标 18 = 描述文字，如 "7连板" / "3天2板"，仅作备注
    下标 5/19 = 梯队列表 theme 及其代码，是本项目唯一 theme 真相
  GetYTFP_BKHX
    历史参数是 Date（大写），不是 Day
    List 保留历史接口源字段；市场动向排名使用开盘啦家数与涨停池题材成交额
    TD 按 TDType 分组：0=反包板 1=首板 2=2连板 … 9=打开高度标注

硬规则：
  - 不含 ST；北交所源行进入排除审计账，不进入打板体系
  - 不含北交所（920/83x 等）
  - 反包板按真实连板数归队，不抬高梯队；仅打 is_fanbao 标记
  - DailyLimitPerformance 每一条源记录都必须被解析或明确记入排除账
  - SJZT 含本项目排除的北交所等口径，只作跨接口参考，不再冒充同口径总数
  - 网络/接口失败 → 立即停；数据校验不符 → 记录并继续，收尾统一报告
"""
from __future__ import annotations

import argparse
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

REQUIRED = (
    "sentiment.json",
    "expression.json",
    "zt_pool.json",
    "sector_ladder.json",
    "_DONE",
)


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
    if not all((dd / name).exists() for name in REQUIRED):
        return False
    if (dd / "_MISMATCH").exists():
        return False
    try:
        pool = _read_json(dd / "zt_pool.json", {})
        audit = pool.get("source_reconciliation") or {}
        return (
            int(audit.get("source_row_count"))
            == int(audit.get("included_count"))
            + int(audit.get("excluded_bse_count"))
            and int(audit.get("included_count")) == len(pool.get("stocks") or [])
        )
    except (TypeError, ValueError):
        return False


def _read_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8-sig"))
    return default


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- parse

def _rows(body: dict) -> list:
    """读取成功响应的股票数组；响应结构异常必须显式失败。"""
    if "info" not in body:
        raise ValueError("响应缺少 info")
    info = body["info"]
    if not isinstance(info, list) or not info:
        raise ValueError(f"响应 info 结构异常: {type(info).__name__}")
    if not isinstance(info[0], list):
        raise ValueError("响应 info[0] 不是股票数组")
    return info[0]


def parse_stock(row: list, pid: int) -> tuple[dict[str, Any] | None, str | None]:
    """原始数组 → 结构化。返回 (item, error)。"""
    if not isinstance(row, list) or len(row) < 23:
        return None, f"原始行长度异常 len={len(row) if isinstance(row, list) else '非数组'}"

    code, name = str(row[0]).strip(), str(row[1]).strip()
    if not code or not name:
        return None, f"代码或名称为空: {row[:3]}"
    theme = str(row[5] or "").strip()
    sector_code = str(row[19] or "").strip()
    if not theme:
        return None, f"{code} {name} 梯队列表 theme(raw[5]) 为空"
    if not sector_code:
        return None, f"{code} {name} 梯队列表 theme 代码(raw[19]) 为空"
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
        # 梯队列表字段是算法唯一 theme；不读取个股详情页属性。
        "theme": theme,
        "sector_code": sector_code,
        # row[12] 为接口概念堆，仅随 raw 保留供源数据审计，禁止进入题材匹配
        "first_limit_ts": row[4],
        "turnover_rate": row[14],
        "amount": row[11],
        "price": row[21],
        "limit_pct": row[22],
        "is_fanbao": False,             # 由 sector_ladder 回填
        "raw": row,
    }, None


def parse_sector_ladder(body: dict) -> tuple[dict, set[str]]:
    """解析板块梯队，返回 (doc, 反包板代码集合)。"""
    sectors, fanbao_codes, fanbao_all = [], set(), []
    for source_position, s in enumerate(body.get("List") or [], 1):
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
            "source_position": source_position,
            "source_meta": {
                key: value
                for key, value in s.items()
                if key != "TD"
            },
            "tiers": tiers,          # 键为连板高度
            "fanbao": fanbao,        # 反包板，不计入 tiers
            "height_marks": height_marks,
        })
    return {"sectors": sectors, "fanbao_all": fanbao_all}, fanbao_codes


# --------------------------------------------------------------------------- pull

def pull_pool(
    client: KaipanlaClient,
    day: str,
) -> tuple[list, dict[str, Any], str | None]:
    pool, excluded_bse, seen = [], [], set()
    source_counts: dict[str, int] = {}
    for pid in range(1, MAX_PID + 1):
        print(f"    pid={pid}/{MAX_PID} ...", flush=True)
        body = client.daily_limit_performance(day, pid)
        if not ok(body):
            return [], {}, f"拉 pid={pid} 失败: {body.get('errmsg') or body.get('errcode')}"
        try:
            rows = _rows(body)
        except ValueError as exc:
            return [], {}, f"pid={pid} 响应结构异常: {exc}"
        source_counts[str(pid)] = len(rows)
        for row in rows:
            item, err = parse_stock(row, pid)
            if err:
                return [], {}, err
            if item is None:
                return [], {}, "涨停源记录未被解析且没有错误原因"
            if item["code"] in seen:
                return [], {}, f"重复代码 {item['code']}（跨 pid 出现）"
            seen.add(item["code"])
            if is_bse(item["code"]):
                excluded_bse.append(item)
            else:
                pool.append(item)
    pool.sort(key=lambda x: (-x["boards"], x["code"]))
    excluded_bse.sort(key=lambda x: (-x["boards"], x["code"]))
    audit = {
        "source_row_count": sum(source_counts.values()),
        "source_counts_by_pid": source_counts,
        "included_count": len(pool),
        "excluded_bse_count": len(excluded_bse),
        "excluded_bse": excluded_bse,
    }
    return pool, audit, None


def validate(pool: list, source_audit: dict[str, Any], sentiment: dict) -> str | None:
    """校验同一来源内的完整记账；跨接口 SJZT 只作范围参考。"""
    info = sentiment.get("info") or {}
    try:
        sjzt = int(info.get("SJZT"))
    except Exception:
        return "sentiment 缺少 SJZT"
    source_count = int(source_audit.get("source_row_count") or 0)
    excluded_count = int(source_audit.get("excluded_bse_count") or 0)
    source_counts = source_audit.get("source_counts_by_pid") or {}
    if set(source_counts) != {str(pid) for pid in range(1, MAX_PID + 1)}:
        return "DailyLimitPerformance 未完整记录 1~5 档响应"
    if len(pool) + excluded_count != source_count:
        return (
            f"DailyLimitPerformance 源行 {source_count}，"
            f"目标市场 {len(pool)} + 明确排除 {excluded_count} 无法对账"
        )
    if sjzt > 0 and source_count == 0:
        return "SJZT 非零但 DailyLimitPerformance 五档合计为零"
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
            # 假期或当日未入库。不同采集源彼此独立，绝不删除同日已有原始证据。
            if dd.exists() and not any(dd.iterdir()):
                dd.rmdir()
            if d < date.today():
                non_trading.add(day)
                _write_json(NON_TRADING_PATH, sorted(non_trading))
            return "skip", None
        return "fail", f"{day} sentiment 失败: {sentiment.get('errmsg') or sentiment.get('errcode')}"

    expression = client.zhangting_expression(day)
    if not ok(expression):
        return "fail", f"{day} expression 失败: {expression.get('errmsg') or expression.get('errcode')}"

    pool, source_audit, err = pull_pool(client, day)
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

    verr = validate(pool, source_audit, sentiment)

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
        "theme_source": {
            "action": "DailyLimitPerformance",
            "field": "stocks[].raw[5]",
            "sector_code_field": "stocks[].raw[19]",
        },
        "source_reconciliation": {
            **source_audit,
            "sentiment_sjzt_reference": int(
                (sentiment.get("info") or {}).get("SJZT")
            ),
            "target_scope_delta_vs_sentiment": (
                int((sentiment.get("info") or {}).get("SJZT")) - len(pool)
            ),
            "contract": (
                "DailyLimitPerformance 源行逐条记账；北交所明确排除；"
                "HisZhangFuDetail.SJZT 与梯队列表并非同一市场范围，仅作参考"
            ),
        },
        "stocks": pool,
    })

    summary = (
        f"目标市场={len(pool)} 源行={source_audit['source_row_count']} "
        f"排除北交所={source_audit['excluded_bse_count']} "
        f"SJZT参考={(sentiment.get('info') or {}).get('SJZT')} "
        f"最高板={max_board} 反包={n_fanbao} "
        f"分布={dict(sorted(counts.items(), key=lambda x: -int(x[0])))}"
    )
    if verr:
        if (dd / "_DONE").exists():
            (dd / "_DONE").unlink()
        (dd / "_MISMATCH").write_text(f"{verr}\n", encoding="utf-8")
        return "mismatch", f"{day} {verr}"
    if (dd / "_MISMATCH").exists():
        (dd / "_MISMATCH").unlink()
    if (dd / "_CURRENT_SNAPSHOT").exists():
        (dd / "_CURRENT_SNAPSHOT").unlink()
    (dd / "_DONE").write_text(f"ok {summary}\n", encoding="utf-8")
    return "ok", summary


# --------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="开盘啦历史数据回灌")
    parser.add_argument("--start", type=date.fromisoformat, default=START)
    parser.add_argument("--end", type=date.fromisoformat, default=END)
    args = parser.parse_args(argv)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    # 约 200 交易日 × 8 请求 × 0.75s ≈ 20 分钟
    client = KaipanlaClient(DATA_DIR, interval_min=0.5, interval_max=1.0)

    state = _read_json(STATE_PATH, {"completed": [], "started_at": None})
    state.setdefault("completed", [])
    if not state.get("started_at"):
        state["started_at"] = datetime.now().isoformat(timespec="seconds")

    non_trading = set(_read_json(NON_TRADING_PATH, []))
    mismatches: list[str] = [
        item
        for item in _read_json(MISMATCH_PATH, [])
        if (RAW_DIR / str(item)[:10] / "_MISMATCH").exists()
    ]
    _write_json(MISMATCH_PATH, mismatches)

    days = trading_days(args.start, args.end)
    todo = [d for d in days if not day_complete(d) and d.isoformat() not in non_trading]

    print(f"DeviceID: {client.device_id}")
    print("间隔 0.5~1s 随机 | 不含ST | 反包不抬梯队 | 每日 8 次请求 | 目标约20分钟")
    print(f"区间 {args.start} ~ {args.end}")
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
        mismatches = [
            item for item in mismatches
            if not str(item).startswith(f"{d.isoformat()} ")
        ]
        _write_json(MISMATCH_PATH, mismatches)
        completed = set(state["completed"])
        completed.add(d.isoformat())
        state["completed"] = sorted(completed)
        state["last_ok"] = d.isoformat()
        state["last_error"] = None
        _write_json(STATE_PATH, state)

    print("-" * 64)
    if mismatches:
        print(f"完成，但有 {len(mismatches)} 天源数据未通过同口径校验：")
        for m in mismatches:
            print(f"  - {m}")
    else:
        print("回灌完成，DailyLimitPerformance 源记录已全部对账。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
