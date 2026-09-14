"""开盘啦复盘数据查询：属性编号、板块涨停宽度、供应商一字标记。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .client import CN_TZ, HIS_URL, KaipanlaClient, ok
from .source import load_day

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "kaipanla"
PAGE_SIZE = 50


def _day(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def _id(value: str) -> str:
    if not value.isdigit() or len(value) != 6:
        raise ValueError("股票或板块编号必须为六位数字")
    return value


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _check_response(body: dict[str, Any], day: str, field: str) -> None:
    if not ok(body):
        raise RuntimeError(f"开盘啦接口失败: {body.get('errmsg') or body.get('errcode')}")
    actual = body.get(field)
    if actual != day and actual != [day]:
        raise RuntimeError(f"响应日期不一致: 请求{day}，返回{actual!r}")


def _member_snapshot(day: str, plate_id: str, pages: list[dict[str, Any]]) -> dict[str, Any]:
    members = []
    seen = set()
    declared = None
    for page in pages:
        _check_response(page, day, "Day")
        count = int(page.get("Count", -1))
        if count <= 0 or (declared is not None and declared != count):
            raise RuntimeError("板块成员总数为空或分页间发生变化，不能记作零")
        declared = count
        rows = page.get("list")
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("板块成员分页缺失")
        for row in rows:
            if not isinstance(row, list) or len(row) < 7:
                raise RuntimeError("板块成员结构异常")
            code = _id(str(row[0]))
            if code in seen:
                raise RuntimeError(f"板块成员重复: {code}")
            seen.add(code)
            members.append({
                "code": code, "name": row[1], "price": row[5],
                "change_pct": row[6], "raw": row,
            })
    if declared is None or len(members) != declared:
        raise RuntimeError(f"板块成员未完整取回: {len(members)}/{declared}")
    return {
        "date": day, "plate_id": plate_id, "provider": "kaipanla",
        "endpoint": HIS_URL, "action": "ZhiShuStockList_W8",
        "captured_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
        "member_count": len(members), "members": members, "raw_pages": pages,
        "historical_membership_verified": False,
        "membership_note": "指定日期行情已核对；接口未证明成员关系和附带标签未被后补。",
    }


def plate_members(day: str, plate_id: str) -> dict[str, Any]:
    day, plate_id = _day(day), _id(plate_id)
    path = DATA_DIR / "plate_members" / day / f"{plate_id}.json"
    if path.exists():
        body = _read(path)
        if body.get("date") != day or body.get("plate_id") != plate_id:
            raise RuntimeError(f"板块缓存身份不一致: {path}")
        checked = _member_snapshot(day, plate_id, body["raw_pages"])
        if body.get("members") != checked["members"] or body.get("member_count") != checked["member_count"]:
            raise RuntimeError(f"板块缓存与原始分页不一致: {path}")
        return body
    client = KaipanlaClient(DATA_DIR)
    pages = []
    index = 0
    while True:
        body = client.plate_members_page(day, plate_id, index)
        _check_response(body, day, "Day")
        count = int(body.get("Count", -1))
        rows = body.get("list")
        if count <= 0 or not isinstance(rows, list) or not rows:
            raise RuntimeError("板块接口返回空数据；请检查编号、日期和分页参数，不能计零")
        pages.append(body)
        index += len(rows)
        if index >= count:
            break
        if len(rows) != PAGE_SIZE:
            raise RuntimeError("板块成员分页提前结束")
    snapshot = _member_snapshot(day, plate_id, pages)
    _write(path, snapshot)
    return snapshot


def breadth(day: str, plate_id: str) -> dict[str, Any]:
    snapshot = plate_members(day, plate_id)
    pool = {row["code"]: row for row in load_day(day)["stocks"]}
    stocks = []
    for member in snapshot["members"]:
        code = member["code"]
        if code not in pool:
            continue
        row = pool[code]
        if abs(float(member["price"]) - float(row["price"])) > 0.005:
            raise RuntimeError(f"{day} {code} 板块行情与当日涨停池价格不一致")
        stocks.append({"code": code, "name": row["name"], "boards": row["boards"]})
    stocks.sort(key=lambda row: (-row["boards"], row["code"]))
    return {
        "date": day, "plate_id": plate_id, "member_count": snapshot["member_count"],
        "limit_count": len(stocks), "stocks": stocks,
        "membership_note": snapshot["membership_note"],
        "source": "开盘啦完整板块成员与同日涨停池按股票代码取交集",
    }


def _ladder_rows(body: dict[str, Any], day: str) -> list[list[Any]]:
    _check_response(body, day, "Date")
    rows = body.get("StockList")
    if not isinstance(rows, list):
        raise RuntimeError("涨停天梯缺少StockList")
    seen = set()
    for row in rows:
        if not isinstance(row, list) or len(row) < 7 or row[6] not in (0, 1):
            raise RuntimeError("涨停天梯一字标记结构异常")
        code = _id(str(row[0]))
        if code in seen:
            raise RuntimeError(f"涨停天梯重复代码: {code}")
        seen.add(code)
        if datetime.fromtimestamp(int(row[3]), CN_TZ).date().isoformat() != day:
            raise RuntimeError(f"涨停天梯股票时间不属于请求日期: {code}")
    return rows


def pool(day: str) -> dict[str, Any]:
    day = _day(day)
    path = DATA_DIR / "raw" / day / "limit_ladder.json"
    if path.exists():
        body = _read(path)
    else:
        body = KaipanlaClient(DATA_DIR).limit_ladder(day)
        _ladder_rows(body, day)
        _write(path, body)
    rows = _ladder_rows(body, day)
    marks = {str(row[0]): row for row in rows}
    stocks = []
    for row in load_day(day)["stocks"]:
        mark = marks.get(row["code"])
        if mark is None or int(mark[2]) != row["boards"]:
            raise RuntimeError(f"{day} {row['code']} 涨停池与天梯缺失或板数冲突")
        stocks.append({
            "code": row["code"], "name": row["name"], "boards": row["boards"],
            "first_limit_time": datetime.fromtimestamp(row["first_limit_ts"], CN_TZ).strftime("%H:%M:%S"),
            "provider_one_price_flag": mark[6],
            "provider_one_price_label": "大单一字" if mark[6] == 1 else "未标一字",
        })
    return {
        "date": day, "count": len(stocks), "stocks": stocks,
        "source": "DailyLimitPerformance + GetZhangTingTianTi.StockList[6]",
        "flag_note": "原样读取供应商大单一字标记；0表示未标注，不扩写为已独立证明非一字。",
    }


def concepts(code: str) -> dict[str, Any]:
    code = _id(code)
    today = datetime.now(CN_TZ).date().isoformat()
    path = DATA_DIR / "concepts_current" / today / f"{code}.json"
    if path.exists():
        body = _read(path)
        if body.get("code") != code or body.get("captured_date") != today:
            raise RuntimeError("属性编号缓存身份不一致")
        return body
    raw = KaipanlaClient(DATA_DIR).stock_concepts(code)
    if not ok(raw) or not isinstance(raw.get("List"), list):
        raise RuntimeError("开盘啦当前属性接口失败")
    body = {
        "code": code, "captured_date": today, "snapshot_mode": "current",
        "concepts": raw["List"], "raw_response": raw,
        "note": "只用于查询板块编号和当前属性说明，不认作历史当天消息。",
    }
    _write(path, body)
    return body


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("breadth", help="指定属性的全市场涨停数量，包含首板与换手板")
    p.add_argument("--plate", required=True)
    p.add_argument("--before", required=True)
    p.add_argument("--day", required=True)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("pool", help="当日涨停名单和供应商一字标记")
    p.add_argument("day")
    p.add_argument("--code")
    p.add_argument("--marked-only", action="store_true", help="仅显示供应商明确标注一字的股票")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("concepts", help="查询当前属性与板块编号")
    p.add_argument("code")
    p.add_argument("--name", help="按属性名称筛选")
    p.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.command == "breadth":
        if _day(args.before) >= _day(args.day):
            parser.error("--before 必须早于 --day")
        previous = breadth(args.before, args.plate)
        current = breadth(args.day, args.plate)
        result = {"previous": previous, "current": current,
                  "count_change": current["limit_count"] - previous["limit_count"]}
        if not args.json:
            for item in (previous, current):
                print(f"{item['date']} {item['limit_count']}只：" + "、".join(r["name"] for r in item["stocks"]))
            print(current["membership_note"])
            return
    elif args.command == "pool":
        result = pool(args.day)
        if args.code:
            result["stocks"] = [r for r in result["stocks"] if r["code"] == _id(args.code)]
        if args.marked_only:
            result["stocks"] = [r for r in result["stocks"] if r["provider_one_price_flag"] == 1]
        if not args.json:
            for row in result["stocks"]:
                print(f"{row['code']} {row['name']} {row['boards']}板 {row['provider_one_price_label']} 首封{row['first_limit_time']}")
            return
    else:
        result = concepts(args.code)
        if args.name:
            result["concepts"] = [r for r in result["concepts"] if args.name in r.get("CName", "")]
        if not args.json:
            for row in result["concepts"]:
                print(f"{row['CCode']} {row['CName']}")
            return
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
