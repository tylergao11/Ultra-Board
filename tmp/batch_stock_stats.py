import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import unicodedata
import urllib.parse
import urllib.request


ROOT = Path(r"C:\Ai\Ultra-Board")
RAW = ROOT / "data" / "kaipanla" / "raw"

TARGETS = [
    ("2025-01-02", "美邦股份"),
    ("2025-01-09", "金奥博"),
    ("2025-01-14", "冀凯股份"),
    ("2025-01-17", "兴业股份"),
    ("2025-01-22", "新炬网络"),
    ("2025-02-13", "杭齿前进"),
    ("2025-02-21", "庄园牧场"),
    ("2025-02-27", "天正电气"),
    ("2025-03-03", "宁水集团"),
    ("2025-03-04", "信隆健康"),
    ("2025-03-06", "湖北广电"),
    ("2025-03-11", "明牌珠宝"),
    ("2025-03-12", "奇精机械"),
    ("2025-03-13", "神开股份"),
    ("2025-03-21", "尤夫股份"),
    ("2025-03-27", "凯美特气"),
    ("2025-04-02", "海鸥住工"),
    ("2025-04-03", "国芳集团"),
    ("2025-04-10", "泰慕士"),
    ("2025-04-14", "国光连锁"),
    ("2025-04-15", "安记食品"),
    ("2025-04-16", "天保基建"),
    ("2025-04-18", "天元股份"),
    ("2025-04-25", "渝三峡A"),
    ("2025-05-06", "春光科技"),
    ("2025-05-07", "成飞集成"),
    ("2025-05-13", "南京港"),
    ("2025-05-15", "郑中设计"),
    ("2025-05-15", "丽人丽妆"),
    ("2025-05-21", "汇得科技"),
    ("2025-05-22", "尚纬股份"),
    ("2025-05-27", "德邦股份"),
    ("2025-05-30", "共创草坪"),
    ("2025-06-03", "金时科技"),
    ("2025-06-09", "北矿科技"),
    ("2025-06-13", "准油股份"),
    ("2025-06-13", "山东墨龙"),
    ("2025-06-17", "诺德股份"),
    ("2025-06-19", "湘潭电化"),
    ("2025-06-24", "大东南"),
    ("2025-06-26", "诚邦股份"),
    ("2025-07-03", "森林包装"),
    ("2025-07-03", "华光环能"),
    ("2025-07-03", "金安国纪"),
    ("2025-07-11", "兰生股份"),
    ("2025-07-11", "上海物贸"),
    ("2025-07-21", "西藏旅游"),
    ("2025-08-11", "大元泵业"),
    ("2025-08-14", "济民健康"),
    ("2025-08-15", "科森科技"),
    ("2025-08-18", "园林股份"),
    ("2025-09-03", "首开股份"),
    ("2025-09-12", "香江控股"),
    ("2025-09-16", "杭电股份"),
    ("2025-09-19", "华软科技"),
    ("2025-09-22", "蓝丰生化"),
    ("2025-10-14", "大有能源"),
    ("2025-10-14", "远大控股"),
    ("2025-10-28", "合富中国"),
    ("2025-11-04", "摩恩电气"),
    ("2025-11-06", "孚日股份"),
    ("2025-11-07", "三木集团"),
    ("2025-11-10", "人民同泰"),
    ("2025-11-12", "九牧王"),
    ("2025-11-14", "中水渔业"),
    ("2025-11-15", "实达集团"),
    ("2025-11-24", "金富科技"),
    ("2025-11-27", "道明光学"),
    ("2025-12-02", "安记食品"),
    ("2025-12-03", "龙洲股份"),
    ("2025-12-05", "东百集团"),
    ("2025-12-08", "再升科技"),
    ("2025-12-11", "百大集团"),
    ("2025-12-18", "神剑股份"),
    ("2025-12-24", "大业股份"),
    ("2026-01-05", "银河电子"),
    ("2026-03-12", "三房巷"),
    ("2026-03-16", "华电辽能"),
    ("2026-03-24", "美诺华"),
    ("2026-03-27", "津药药业"),
    ("2026-04-02", "汇源通信"),
    ("2026-04-07", "华远控股"),
    ("2026-04-09", "圣阳股份"),
    ("2026-04-17", "金螳螂"),
    ("2026-04-22", "水发燃气"),
    ("2026-05-06", "大唐发电"),
    ("2026-05-08", "蒙娜丽莎"),
    ("2026-05-25", "香江控股"),
    ("2026-06-01", "大有能源"),
    ("2026-07-10", "哈药股份"),
    ("2026-07-16", "立新能源"),
    ("2026-07-21", "长缆科技"),
    ("2026-07-27", "传智教育"),
    ("2026-07-28", "一鸣食品"),
    ("2026-07-31", "豪尔赛"),
    ("2026-08-04", "百花医药"),
    ("2026-08-04", "宝鼎科技"),
    ("2026-08-07", "秦安股份"),
    ("2026-08-19", "汉森制药"),
    ("2026-08-20", "深中华A"),
]


def market_row(day, name):
    path = RAW / day / "zt_pool.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    matches = [x for x in doc["stocks"] if x.get("name") == name]
    if not matches:
        # Tolerate ST prefixes/suffixes and spaces if the display name changed.
        aliases = {"安通股份": "安通控股"}
        wanted = aliases.get(name, name)
        compact = unicodedata.normalize("NFKC", wanted).replace(" ", "").upper()
        matches = [
            x for x in doc["stocks"]
            if compact in unicodedata.normalize("NFKC", x.get("name", "")).replace("*", "").replace("ST", "").replace(" ", "").upper()
        ]
    if len(matches) != 1:
        raise RuntimeError(f"market match {day} {name}: {[(x.get('code'), x.get('name')) for x in matches]}")
    x = matches[0]
    return {
        "date": day,
        "name": name,
        "snapshot_name": x["name"],
        "code": x["code"],
        "price": float(x["price"]),
        "float_cap_yi": float(x["raw"][13]) / 100_000_000,
        "snapshot_path": str(path),
    }


def parse_date(value):
    if not value:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def fetch_holders(row):
    suffix = "SH" if row["code"].startswith(("6", "68")) else "SZ"
    secucode = f'{row["code"]}.{suffix}'
    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    params = {
        "reportName": "RPT_F10_EH_FREEHOLDERS",
        "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": 1,
        "pageSize": 200,
        "sortTypes": -1,
        "sortColumns": "END_DATE",
        "source": "HSF10",
        "client": "PC",
    }
    last_error = None
    for _ in range(3):
        try:
            request_url = url + "?" + urllib.parse.urlencode(params)
            request = urllib.request.Request(request_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            data = (payload.get("result") or {}).get("data") or []
            cutoff = dt.date.fromisoformat(row["date"])
            eligible = []
            for item in data:
                end_date = parse_date(item.get("END_DATE"))
                notice_date = parse_date(item.get("NOTICE_DATE") or item.get("UPDATE_DATE"))
                if end_date and notice_date and end_date <= cutoff and notice_date <= cutoff:
                    eligible.append(item)
            if not eligible:
                raise RuntimeError(f"no disclosed holder report before {cutoff}")
            selected_end = max(parse_date(x["END_DATE"]) for x in eligible)
            selected = [x for x in eligible if parse_date(x["END_DATE"]) == selected_end and int(x.get("HOLDER_RANK") or 999) <= 10]
            # De-duplicate defensive repeats by rank/name/holding.
            unique = {}
            for x in selected:
                unique[(x.get("HOLDER_RANK"), x.get("HOLDER_NAME"), x.get("HOLD_NUM"))] = x
            selected = list(unique.values())
            if len(selected) < 10:
                raise RuntimeError(f"only {len(selected)} top holders for {selected_end}")
            selected.sort(key=lambda x: (int(x.get("HOLDER_RANK") or 999), x.get("HOLDER_NAME") or ""))
            return {
                **row,
                "holder_report_date": selected_end.isoformat(),
                "holder_notice_date": max(parse_date(x.get("NOTICE_DATE") or x.get("UPDATE_DATE")) for x in selected).isoformat(),
                "top10_num": sum(float(x.get("HOLD_NUM") or 0) for x in selected),
                "top10_pct": sum(float(x.get("FREE_HOLDNUM_RATIO") or 0) for x in selected),
                "holder_count": len(selected),
                "holder_api": request_url,
            }
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"{row['date']} {row['name']} {secucode}: {last_error}")


market = []
errors = []
for day, name in TARGETS:
    try:
        market.append(market_row(day, name))
    except Exception as exc:
        errors.append(str(exc))

results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
    future_map = {pool.submit(fetch_holders, row): row for row in market}
    for future in concurrent.futures.as_completed(future_map):
        try:
            results.append(future.result())
        except Exception as exc:
            errors.append(str(exc))

order = {(d, n): i for i, (d, n) in enumerate(TARGETS)}
results.sort(key=lambda x: order[(x["date"], x["name"])])

out = ROOT / "tmp" / "batch_stock_stats_results.json"
out.write_text(json.dumps({"results": results, "errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"result_count": len(results), "error_count": len(errors), "errors": errors}, ensure_ascii=False, indent=2))
for x in results:
    print(f'{x["date"]}\t{x["name"]}\t{x["code"]}\t{x["top10_pct"]:.2f}%\t{x["price"]:.2f}\t{x["float_cap_yi"]:.2f}\t{x["holder_report_date"]}\t{x["holder_notice_date"]}')
