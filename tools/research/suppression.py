"""Repair suppression dates without reclassifying replenishment or themes."""
import hashlib
import json
from .batch import _daily_row, _global_pool, _in_suppression_scope, _latest_attributes
from .derive import Resolver, _match_row


def current_day(details, focus_date):
    matches = [day for day in details if day.get("日期") == focus_date]
    if len(matches) != 1:
        raise ValueError(f"{focus_date}: expected exactly one saved suppression day")
    return matches


def repair(store, from_date, to_date, preview=False):
    store.sync_rules()
    c = store.connect()
    changed = []
    checked = 0
    requests = []
    try:
        rules = json.loads((store.root / "data/store/rules/static_rules.json").read_text(encoding="utf-8"))["rules"]
        resolver = Resolver(c, rules, {})
        batch_key = c.execute("SELECT value FROM store_meta WHERE key='current_batch_key'").fetchone()[0]
        pools = {}
        for row in c.execute("SELECT * FROM current_static_research WHERE substr(legacy_record_key,8) BETWEEN ? AND ?",
                             (from_date, to_date)).fetchall():
            raw = json.loads(row["raw_json"])
            if raw.get("压制判断") is None:
                continue  # No existing suppression decision to repair.
            details = raw.get("一字压制核验明细") or []
            date = row["legacy_record_key"].split("|")[1]
            saved_days = [d for d in details if d.get("日期") == date]
            if len(saved_days) == 1 and "更高一字票" in saved_days[0]:
                days = current_day(details, date)
            elif len(saved_days) == 1 and "逐只属性核验" in saved_days[0]:
                old = saved_days[0]
                days = [{"日期":date,"候选身位":old["候选高度"],"更高一字票":[
                    {"股票代码":h["高位代码"],"股票名称":h["高位股票"],"身位":h["高位高度"],
                     "命中":h["命中候选主炒属性"],"来源":h.get("来源",[]),"依据":h.get("依据")}
                    for h in old["逐只属性核验"]]}]
            else:
                stock_id = c.execute("SELECT id FROM stocks WHERE code=?",(row["legacy_record_key"][:6],)).fetchone()[0]
                candidate = _daily_row(c, stock_id, date)
                if not candidate or not candidate.get("strict_one_word"):
                    raise ValueError(f"{row['legacy_record_key']}: current day is not a strict one-price day")
                if date not in pools:
                    pools[date] = _global_pool(c, "strict_one_word", date, batch_key)
                members = []
                cand_code = row["legacy_record_key"][:6]
                for high in pools[date]:
                    if high["stock_id"] == stock_id:
                        continue
                    if not _in_suppression_scope(cand_code, candidate["board_height"],
                                                 high.get("code"), high.get("board_height")):
                        continue
                    high = dict(high, attributes=_latest_attributes(c, high["stock_id"]))
                    members.append(_match_row(high,date,raw["唯一主炒作属性"],resolver))
                days = [{"日期":date,"候选身位":candidate["board_height"],"更高一字票":members}]
            checked += 1
            hits = [h for d in days for h in d["更高一字票"] if h.get("命中")]
            result = "压制" if hits else "非压制"
            basis = "；".join(f"{date} {h['股票名称']}({h['股票代码']}) {h['身位']}板 具备{raw['唯一主炒作属性']}" for h in hits)
            basis = basis or f"本次首开前一字日{date}无更高一字票命中{raw['唯一主炒作属性']}；更早日期不延续压制。"
            updates = {"一字压制核验明细":days,"压制判断":result,"压制依据":basis,
                       "静态筛选结论":"通过" if result == "非压制" and raw.get("补涨判断") == "先锋" else "不通过"}
            checks = []
            for check in c.execute("SELECT * FROM research_checks WHERE static_research_id=?", (row["id"],)):
                item = {"check_type":check["check_type"],"subject_stock_id":check["subject_stock_id"],
                        "outcome":check["outcome"],"basis":check["basis"],"sources":json.loads(check["source_json"]),
                        "raw":json.loads(check["raw_json"])}
                if item["check_type"] == "一字压制核验明细":
                    item.update(outcome=result,basis=basis,raw=days)
                checks.append(item)
            request = {"record_key":row["legacy_record_key"],"kind":"static","updates":updates,
                       "checks":checks,"confirmation_status":row["confirmation_status"]}
            request["request_id"] = "suppression-date-" + hashlib.sha256(json.dumps(request,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            requests.append((request, raw))
            if str(raw.get("压制判断") or "").startswith(("压", "被", "有")) != bool(hits):
                changed.append({"record_key":row["legacy_record_key"],"股票":raw.get("股票"),
                                "出生日期":raw.get("补涨题材日期"),"首开日期":raw.get("首开日期"),
                                "补涨判断":raw.get("补涨判断"),"公告污染":raw.get("公告污染"),
                                "旧压制":raw.get("压制判断"),"新压制":result})
        if not preview:
            with store.immediate(c):
                for request, before in requests:
                    store.write_research(request,c)
                    after = json.loads(c.execute("SELECT raw_json FROM current_static_research WHERE legacy_record_key=?",
                                                 (request["record_key"],)).fetchone()[0])
                    for key in ("补涨判断","映射依据","补涨映射明细","唯一主炒作属性","公告污染","出生当日补涨高标"):
                        if before.get(key) != after.get(key):
                            raise RuntimeError(f"unrelated field changed: {request['record_key']} {key}")
            store.export_all(publish_root=True)
        return {"checked":checked,"changed":len(changed),"records":changed,"preview":preview}
    finally:
        c.close()
