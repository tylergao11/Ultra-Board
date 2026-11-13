"""Local theme inputs -> dated fact matching -> current static research + display.

No network, trading calculations, or stock-specific decisions live here.
"""
from __future__ import annotations

import hashlib
import json
import time
from contextlib import nullcontext
from datetime import date as calendar_date
from .batch import (_json, _read_json, _select_records, _record_facts,
                    _trading_dates, _source_values, _actual_board_sequence,
                    _actual_first_board_date, _actual_next_first_board_date, static_request)


class MissingInput(ValueError):
    pass




class Resolver:
    def __init__(self, connection, rules, edits):
        self.c = connection
        self.aliases = rules["自动匹配"]["属性归并"]
        if not isinstance(self.aliases,dict) or any(not isinstance(k,str) or not isinstance(v,str) or not v.strip()
                                                  for k,v in self.aliases.items()):
            raise ValueError("属性归并应填写题材名称到名称的映射")
        for name in self.aliases:
            self.canonical(name)
        self.inputs = {}
        self.rounds = {}
        self.dependencies = set()
        self.changed_inputs = {}
        for row in connection.execute("SELECT * FROM research_theme_inputs"):
            self.inputs[(row["stock_id"], row["first_board_date"])] = {
                "main_theme": row["main_theme"], "basis": row["basis"],
                "sources": json.loads(row["sources_json"]),
                "attributes": json.loads(row["attribute_overrides_json"]),
            }
        self.edits = edits

    def canonical(self, theme):
        seen = set()
        while theme in self.aliases and self.aliases[theme] != theme:
            if theme in seen:
                raise ValueError(f"属性归并存在循环：{theme}")
            seen.add(theme)
            theme = self.aliases[theme]
        return theme

    def round_key(self, stock_id, date):
        key = (stock_id, date)
        if key not in self.rounds:
            start = _actual_first_board_date(self.c, stock_id, date)
            if not start:
                raise MissingInput(f"股票ID {stock_id} 在 {date} 前缺少实际首板行情")
            self.rounds[key] = (stock_id, start)
        result = self.rounds[key]
        self.dependencies.add(result)
        return result

    def theme(self, stock_id, date, required=False):
        key = self.round_key(stock_id, date)
        if key not in self.inputs:
            # Reuse an existing judgement only within the same actual launch.
            rows = self.c.execute(
                """SELECT r.main_theme,r.raw_json,r.evidence_snapshot_json FROM current_static_research r
                   JOIN first_open_events e ON e.id=r.first_open_event_id
                   JOIN launch_rounds l ON l.id=e.launch_round_id
                   WHERE l.stock_id=? AND l.first_board_date=? AND r.main_theme IS NOT NULL
                   AND r.research_status<>'unresearched' ORDER BY l.focus_date DESC""", key).fetchall()
            themes = {r["main_theme"] for r in rows if r["main_theme"]}
            if len(themes) > 1 and key not in self.edits:
                raise MissingInput(f"股票ID {stock_id} / {key[1]} 存在多个已保存主炒：{sorted(themes)}")
            if themes:
                raw = json.loads(rows[0]["raw_json"])
                self.inputs[key] = {"main_theme": rows[0]["main_theme"],
                                    "basis": raw.get("唯一主炒依据") or "沿用本轮已保存题材判断",
                                    "sources": sorted(_source_values(raw.get("首二原始证据", [])))
                                               or json.loads(rows[0]["evidence_snapshot_json"]),
                                    "attributes": {}}
                self.changed_inputs[key] = self.inputs[key]
        if key in self.edits:
            old = self.inputs.get(key, {})
            edit = self.edits[key]
            value = dict(old, **edit)
            if not value.get("main_theme"):
                raise MissingInput(f"股票ID {stock_id} / {key[1]} 缺少本轮主炒判断")
            if not value.get("basis") or ("main_theme" in edit and edit["main_theme"] != old.get("main_theme") and "basis" not in edit):
                value["basis"] = "用户调整本轮主炒为" + value["main_theme"]
            value.setdefault("sources", [])
            value.setdefault("attributes", {})
            if value != old:
                self.inputs[key] = value
                self.changed_inputs[key] = value
        value = self.inputs.get(key)
        if required and not value:
            code = self.c.execute("SELECT code FROM stocks WHERE id=?", (stock_id,)).fetchone()[0]
            raise MissingInput(f"{code}|{key[1]} 缺少本轮主炒判断")
        return value

    def attributes(self, member, date):
        attributes = member["attributes"]
        if attributes.get("snapshot_status") == "missing":
            raise MissingInput(f"{member['code']} 缺少完整属性快照；影响 {date} 映射")
        value = self.theme(member["stock_id"], date)
        tags = {self.canonical(t) for t in attributes["tags"]}
        sources = set(attributes.get("sources", []))
        if value:
            tags.add(self.canonical(value["main_theme"]))
            sources.update(value["sources"])
            override = value["attributes"]
            if override and override.get("from_date", "0000") <= date <= override.get("to_date", "9999"):
                tags.update(self.canonical(t) for t in override.get("add", []))
                tags.difference_update(self.canonical(t) for t in override.get("remove", []))
                sources.update(override.get("sources", []))
        return tags, sorted(sources)

    def register_dependencies(self, fact):
        """Capture every dependency before a missing input can stop matching."""
        subjects = [(fact["identity"]["stock_id"],fact["identity"]["first_board_date"])]
        subjects += [(h["stock_id"],fact["high_pool"]["date"]) for h in fact["high_pool"]["members"]]
        subjects += [(h["stock_id"],d["date"]) for d in fact["strict_one_word_days"] for h in d["higher_members"]]
        pool = fact["potential_competitor_candidates"]
        subjects += [(h["stock_id"],pool["date"]) for h in pool["members"]]
        missing = []
        for stock_id,date in subjects:
            try:
                self.round_key(stock_id,date)
            except MissingInput as exc:
                missing.append(str(exc))
        if missing:
            raise MissingInput("；".join(sorted(set(missing))))

    def verify_sequence(self, stock_id, date):
        start = self.round_key(stock_id,date)[1]
        rows = _actual_board_sequence(self.c, stock_id, start, date)
        if not rows or rows[-1][0] != date or [r[1] for r in rows] != list(range(1,len(rows)+1)):
            raise MissingInput(f"股票ID {stock_id} / {date} 连续涨停序列缺项，需补齐本轮行情")
        # A suspension can span market trading days. Use the source's continuous
        # board heights, so a missing stock quote is not treated as a broken run.


def _match_row(member, date, theme, resolver):
    tags, sources = resolver.attributes(member, date)
    hit = resolver.canonical(theme) in tags
    return {"股票代码": member["code"], "股票名称": member["name"],
            "日期": date, "身位": member.get("board_height"), "命中": hit,
            "命中属性": theme if hit else None, "完整有效属性": sorted(tags),
            "依据": f"有效属性{'具备' if hit else '不具备'}{theme}",
            "来源": sorted(set(sources) | _source_values(member.get("source")))}


def derive_record(fact, resolver, announcement=None):
    identity = fact["identity"]
    if not fact["strict_one_word_days"]:
        raise MissingInput(f"{fact['record_key']} 缺少本轮实际严格一字日，需核对行情与事件归属")
    subject = dict(identity, attributes=fact["attributes"])
    own = resolver.theme(identity["stock_id"], identity["first_board_date"], True)
    resolver.verify_sequence(identity["stock_id"],identity["focus_date"])
    theme = own["main_theme"]
    tags, sources = resolver.attributes(subject, identity["first_board_date"])
    replenishment = []
    for high in fact["high_pool"]["members"]:
        judgement = resolver.theme(high["stock_id"], fact["high_pool"]["date"], True)
        high["confirmed_main_theme"] = judgement["main_theme"]
        high["main_theme_basis"] = judgement["basis"]
        high["main_theme_sources"] = judgement["sources"]
        direction = resolver.canonical(judgement["main_theme"])
        replenishment.append({"股票代码": high["code"], "股票名称": high["name"],
                              "身位": high["board_height"], "状态": high["status"],
                              "高标主炒": judgement["main_theme"], "命中": direction in tags,
                              "来源": sorted(set(sources + judgement["sources"]) | _source_values(high["source"]))})
    suppression = []
    for day in fact["strict_one_word_days"]:
        suppression.append({"日期": day["date"], "候选身位": day["candidate_height"],
                            "更高一字票": [_match_row(h, day["date"], theme, resolver) for h in day["higher_members"]]})
    replen_hits = [h for h in replenishment if h["命中"]]
    suppress_hits = [(d["日期"], h) for d in suppression for h in d["更高一字票"] if h["命中"]]
    passed = not replen_hits and not suppress_hits
    competitors = []
    pool = fact["potential_competitor_candidates"]
    # Retain dependencies even for a currently rejected candidate.
    for member in pool["members"]:
        resolver.round_key(member["stock_id"], pool["date"])
        if passed:
            match = _match_row(member, pool["date"], theme, resolver)
            if match["命中"]:
                competitors.append(match)
    raw = fact["current_static_raw"]
    announcement = announcement or {}
    pollution = announcement.get("pollution", raw.get("公告污染"))
    basis = announcement.get("basis", raw.get("公告污染依据"))
    if not isinstance(pollution, bool) or not basis:
        raise MissingInput(f"{fact['record_key']} 缺少公告判断或依据")
    if "sources" in announcement:
        fact["announcement_sources"] = announcement["sources"]
    else:
        fact["announcement_sources"] = sorted(set(fact["announcement_sources"]) | set(raw.get("公告污染来源", [])))
    brief = lambda h: f"{h['股票名称']}({h['股票代码']}) {h['身位']}板"
    return {"record_key": fact["record_key"], "static": {
        "main_theme": theme, "main_theme_basis": own["basis"],
        "replenishment_result": "补涨" if replen_hits else "非补涨",
        "mapping_basis": (f"首板日 {identity['first_board_date']} 高标 {brief(replen_hits[0])} 主炒"
                          f"{replen_hits[0]['高标主炒']}，候选完整有效属性命中。" if replen_hits else
                          f"首板日 {identity['first_board_date']} 的 {len(replenishment)} 只合格高标主炒逐项映射，候选完整有效属性均无命中。"),
        "replenishment_details": replenishment,
        "suppression_result": "有一字压制" if suppress_hits else "无一字压制",
        "suppression_basis": ("；".join(f"{date} {brief(h)} 具备{theme}" for date, h in suppress_hits)
                              if suppress_hits else f"逐日核对 {len(suppression)} 个实际一字日的全部更高一字票，有效属性均未命中{theme}。"),
        "suppression_details": suppression, "competitors": competitors,
        "announcement_pollution": pollution, "announcement_basis": basis,
        "additional_evidence": sorted(set(own["sources"]) | set(raw.get("公告污染来源", []))),
    }}


def _affected_keys(connection, changes, minimum=4):
    keys = set()
    for stock_id, start in changes:
        keys.update(r[0] for r in connection.execute(
            "SELECT record_key FROM research_dependencies WHERE stock_id=? AND first_board_date=?", (stock_id, start)))
        old = connection.execute("SELECT main_theme FROM research_theme_inputs WHERE stock_id=? AND first_board_date=?",
                                 (stock_id,start)).fetchone()
        if not old:
            old = connection.execute("""SELECT r.main_theme FROM current_static_research r
                JOIN first_open_events e ON e.id=r.first_open_event_id JOIN launch_rounds l ON l.id=e.launch_round_id
                WHERE l.stock_id=? AND l.first_board_date=? AND r.main_theme IS NOT NULL LIMIT 1""", (stock_id,start)).fetchone()
        if old and (changes[(stock_id,start)].get("main_theme", old[0]) == old[0]
                    and "attributes" not in changes[(stock_id,start)]):
            continue
        # Also find previously researched records before automatic dependencies were registered.
        end = _actual_next_first_board_date(connection, stock_id, start) or "9999"
        rows = connection.execute("""SELECT r.legacy_record_key,l.stock_id,l.first_board_date,l.focus_date,e.event_date
            FROM current_static_research r JOIN first_open_events e ON e.id=r.first_open_event_id
            JOIN launch_rounds l ON l.id=e.launch_round_id WHERE r.research_status<>'unresearched'
            AND COALESCE(e.event_date,l.focus_date)>=? AND l.first_board_date<?""", (start, end)).fetchall()
        for row in rows:
            if row["stock_id"] == stock_id and row["first_board_date"] == start:
                keys.add(row["legacy_record_key"])
                continue
            # Restrict to a date on which this round was in a relevant comparison pool.
            last = row["event_date"] or row["focus_date"]
            high = connection.execute("""SELECT 1 FROM daily_market h WHERE h.stock_id=?
                AND h.source_type='kaipanla_limit_pool' AND h.trade_date>=? AND h.trade_date<?
                AND ((h.board_height>=? AND h.trade_date IN (?,
                    (SELECT MAX(trade_date) FROM daily_market WHERE source_type='kaipanla_limit_pool' AND trade_date<?)))
                  OR (h.strict_one_word=1 AND EXISTS (SELECT 1 FROM daily_market d WHERE d.stock_id=?
                    AND d.source_type='kaipanla_limit_pool' AND d.trade_date=h.trade_date
                    AND d.trade_date BETWEEN ? AND ? AND d.strict_one_word=1 AND d.board_height<h.board_height))
                  OR (h.trade_date=(SELECT MAX(trade_date) FROM daily_market WHERE source_type='kaipanla_limit_pool' AND trade_date<?)
                    AND h.board_height >= COALESCE((SELECT board_height FROM daily_market d WHERE d.stock_id=?
                        AND d.trade_date=h.trade_date AND d.source_type='kaipanla_limit_pool'),999))) LIMIT 1""",
                (stock_id,start,end,minimum,row["first_board_date"],row["first_board_date"],row["stock_id"],
                 row["first_board_date"],last,last,row["stock_id"])).fetchone()
            if high:
                keys.add(row["legacy_record_key"])
    return keys


def _parse_edits(connection, payload):
    edits = {}
    for item in payload.get("themes", []):
        row = connection.execute("SELECT id FROM stocks WHERE code=?", (item["code"],)).fetchone()
        if not row:
            raise ValueError(f"未知股票代码 {item['code']}")
        key = (row[0], item["first_board_date"])
        actual = _actual_first_board_date(connection, row[0], item["first_board_date"])
        if actual != item["first_board_date"]:
            raise ValueError(f"{item['code']}|{item['first_board_date']} 缺少实际首板行情")
        edit = {k: item[k] for k in ("main_theme", "basis", "sources", "attributes") if k in item}
        if "main_theme" in edit and (not isinstance(edit["main_theme"], str) or not edit["main_theme"].strip()):
            raise ValueError("主炒题材须为一个非空值")
        if "basis" in edit and not isinstance(edit["basis"],str):
            raise ValueError("basis 须填写文字依据")
        if "sources" in edit and (not isinstance(edit["sources"],list) or any(not isinstance(s,str) for s in edit["sources"])):
            raise ValueError("sources 须填写来源列表")
        override = edit.get("attributes")
        if "attributes" in edit and not isinstance(override,dict):
            raise ValueError("attributes 须填写包含 add/remove 的对象，清除例外使用空对象")
        if override and (not override.get("basis") or not override.get("sources")):
            raise ValueError("时点属性例外需填写 basis 和 sources")
        if override:
            for name in ("add","remove","sources"):
                values = override.get(name,[])
                if not isinstance(values,list) or any(not isinstance(v,str) or not v for v in values):
                    raise ValueError(f"attributes.{name} 须填写文字列表")
            for name in ("from_date","to_date"):
                if name in override:
                    calendar_date.fromisoformat(override[name])
            if override.get("from_date","0000") > override.get("to_date","9999"):
                raise ValueError("时点属性例外的起止日期颠倒")
        if not edit:
            raise ValueError("题材输入为空")
        if "main_theme" not in edit:
            known = connection.execute("SELECT 1 FROM research_theme_inputs WHERE stock_id=? AND first_board_date=?",key).fetchone()
            if not known:
                known = connection.execute("""SELECT COUNT(DISTINCT r.main_theme) FROM current_static_research r
                    JOIN first_open_events e ON e.id=r.first_open_event_id JOIN launch_rounds l ON l.id=e.launch_round_id
                    WHERE l.stock_id=? AND l.first_board_date=? AND r.main_theme IS NOT NULL""",key).fetchone()[0] == 1
            if not known:
                raise ValueError(f"{item['code']}|{item['first_board_date']} 请在同一项填写 main_theme")
        previous = edits.get(key,{})
        if any(k in previous and previous[k] != v for k,v in edit.items()):
            raise ValueError(f"{item['code']}|{item['first_board_date']} 在同一提交内有冲突输入")
        edits[key] = dict(previous,**edit)
    return edits


def judgement_slots(store, facts, existing):
    """Show each unresolved shared high theme once; candidates already have their own input."""
    connection = store.connect()
    try:
        resolver = Resolver(connection, _read_json(store.root / "data/store/rules/static_rules.json")["rules"], {})
        seen = {(r["identity"]["code"],r["identity"]["first_board_date"]) for r in facts}
        slots = {(r["code"],r["first_board_date"]):r for r in existing}
        for fact in facts:
            for high in fact["high_pool"]["members"]:
                if not high["first_two"]:
                    continue
                start = high["first_two"][0]["date"]
                key = (high["code"],start)
                if key in seen:
                    continue
                seen.add(key)
                if not resolver.theme(high["stock_id"], start):
                    slots.setdefault(key, {"code":high["code"],"first_board_date":start,"main_theme":None,
                                           "basis":None,"sources":sorted(_source_values(high["first_two"]))})
        return list(slots.values())
    finally:
        connection.close()


def commit_judgements(store, facts, decisions, publish=True, receipt=None):
    by_key = {f["record_key"]:f for f in facts["records"]}
    payload = {"themes":[v for v in decisions.get("high_themes", []) if v.get("main_theme")], "announcements":{}}
    keys, deferred = [], []
    for item in decisions["records"]:
        key = item["record_key"]
        if item.get("defer_reason"):
            deferred.append({"record_key":key,"reason":item["defer_reason"]})
            continue
        fact = by_key[key]
        identity, value = fact["identity"], item["static"]
        keys.append(key)
        if value.get("main_theme") or value.get("main_theme_basis"):
            edit = {"code":identity["code"],"first_board_date":identity["first_board_date"],
                    "sources":sorted(_source_values(fact["first_two"]) | set(value.get("additional_evidence") or []))}
            if value.get("main_theme"):
                edit["main_theme"] = value["main_theme"]
            if value.get("main_theme_basis"):
                edit["basis"] = value["main_theme_basis"]
            payload["themes"].append(edit)
        if isinstance(value.get("announcement_pollution"),bool) or value.get("announcement_basis"):
            pollution = value.get("announcement_pollution")
            payload["announcements"][key] = {"pollution":pollution if isinstance(pollution,bool) else fact["current_static_raw"].get("公告污染"),
                "basis":value.get("announcement_basis") or fact["current_static_raw"].get("公告污染依据"),
                "sources":sorted(set(fact["announcement_sources"]) | set(value.get("additional_evidence") or []))}
    if not keys and not payload["themes"]:
        return {"complete":0,"deferred":deferred}
    if receipt:
        receipt = dict(receipt,phase="static",record_keys=keys)
    result = recompute(store,keys,payload,publish=publish,receipt=receipt)
    result["deferred"] = deferred
    return result


def recompute(store, record_keys=None, inputs=None, preview=False, publish=True, export_root=None,
              publish_root=True, verify_saved=False, receipt=None):
    started = time.perf_counter()
    payload = {} if inputs is None else inputs
    if not isinstance(payload,dict) or set(payload)-{"themes","announcements","record_keys"}:
        raise ValueError("输入字段为 themes、announcements、record_keys")
    if not isinstance(payload.get("themes",[]),list) or any(not isinstance(v,dict) for v in payload.get("themes",[])):
        raise ValueError("themes 须为题材输入列表")
    if not isinstance(payload.get("announcements",{}),dict):
        raise ValueError("announcements 须按记录键填写")
    if not isinstance(payload.get("record_keys",[]),list) or any(not isinstance(v,str) for v in payload.get("record_keys",[])):
        raise ValueError("record_keys 须为记录键列表")
    if inputs is not None and not record_keys and not any(payload.get(k) for k in ("themes","announcements","record_keys")):
        raise ValueError("输入文件没有待处理的题材、公告或记录键")
    connection = store.connect()
    try:
        store.apply_migrations(connection)
        store.sync_rules()
        connection.execute("BEGIN" if preview else "BEGIN IMMEDIATE")
        rules = _read_json(store.root / "data/store/rules/static_rules.json")["rules"]
        edits = _parse_edits(connection, payload)
        parameters = rules["补涨时间参数"]
        minimum = min(parameters["前序最低连续板数"],parameters["当日断板前最低连续板数"])
        keys = set(record_keys or payload.get("record_keys", [])) | set(payload.get("record_keys", [])) | _affected_keys(connection, edits, minimum)
        keys.update(payload.get("announcements", {}))
        if not keys and not edits:
            keys = {r[0] for r in connection.execute("SELECT DISTINCT record_key FROM research_dependencies")}
        resolver = Resolver(connection, rules, edits)
        # Explicit input can also concern a high stock without a first-open candidate.
        for stock_id, date in edits:
            try:
                resolver.theme(stock_id, date, True)
            except MissingInput:
                pass
        announcements = {}
        for key, value in payload.get("announcements",{}).items():
            if not isinstance(value,dict) or set(value)-{"pollution","basis","sources"}:
                raise ValueError(f"{key} 公告字段为 pollution、basis、sources")
            row = connection.execute("SELECT raw_json FROM current_static_research WHERE legacy_record_key=?",(key,)).fetchone()
            if not row:
                raise ValueError(f"未知记录键：{key}")
            raw = json.loads(row[0])
            pollution = value.get("pollution",raw.get("公告污染"))
            basis = value.get("basis",raw.get("公告污染依据"))
            sources = value.get("sources",raw.get("公告污染来源",[]))
            if not isinstance(pollution,bool) or not isinstance(basis,str) or not basis.strip():
                raise ValueError(f"{key} 公告输入需要 pollution 布尔值和 basis")
            if not isinstance(sources,list) or any(not isinstance(v,str) for v in sources):
                raise ValueError(f"{key} 公告 sources 须填写来源列表")
            announcements[key] = {"pollution":pollution,"basis":basis,"sources":sources}
        dates = _trading_dates(connection)
        batch_key = connection.execute("SELECT value FROM store_meta WHERE key='current_batch_key'").fetchone()[0]
        shared = {}
        facts = {"batch_id": "automatic-static", "scope": "static", "records": []}
        decisions = {"records": []}
        dependencies = {}
        blocked = []
        pending_inputs = {}
        timing = {"prepare": 0.0, "match": 0.0}
        requests = []
        for row in _select_records(connection, None, None, sorted(keys)) if keys else []:
            tick = time.perf_counter()
            fact = _record_facts(store, connection, dates, batch_key, row, "static", shared)
            timing["prepare"] += time.perf_counter() - tick
            tick = time.perf_counter()
            resolver.dependencies = set()
            try:
                announcement = announcements.get(fact["record_key"],{})
                if announcement:
                    raw = fact["current_static_raw"]
                    pollution = announcement.get("pollution",raw.get("公告污染"))
                    basis = announcement.get("basis",raw.get("公告污染依据"))
                    sources = announcement.get("sources",raw.get("公告污染来源",[]))
                    pending_inputs[fact["record_key"]] = {"公告污染":pollution,"公告污染依据":basis,"公告污染来源":sources}
                    raw.update(pending_inputs[fact["record_key"]])
                resolver.register_dependencies(fact)
                decision = derive_record(fact, resolver, announcement)
                request = static_request(fact,decision["static"])
                request["confirmation_status"] = row["confirmation_status"]
                request["updates"]["补涨映射明细"] = decision["static"]["replenishment_details"]
                request["updates"]["自动推导"] = True
                request["remove_fields"] += ["自动推导缺项"]
                request["request_id"] = "derive-" + hashlib.sha256(_json({k:v for k,v in request.items() if k != "request_id"}).encode()).hexdigest()
                requests.append(request)
                facts["records"].append(fact)
                decisions["records"].append(decision)
            except (MissingInput, ValueError) as exc:
                blocked.append({"record_key": fact["record_key"], "reason": str(exc)})
            dependencies[fact["record_key"]] = set(resolver.dependencies)
            timing["match"] += time.perf_counter() - tick
        prepared = time.perf_counter()
        results = []
        findings = []
        if verify_saved:
            for request in requests:
                saved = connection.execute("SELECT * FROM current_static_research WHERE legacy_record_key=?",
                                           (request["record_key"],)).fetchone()
                raw = json.loads(saved["raw_json"])
                for name,value in request["updates"].items():
                    if raw.get(name) != value:
                        findings.append(f"{request['record_key']} 当前字段不一致：{name}")
                for name in request["remove_fields"]:
                    if name in raw:
                        findings.append(f"{request['record_key']} 旧字段残留：{name}")
                checks = [dict(r) for r in connection.execute("SELECT check_type,outcome,basis,source_json,raw_json FROM research_checks WHERE static_research_id=? ORDER BY id",(saved["id"],))]
                expected = [{"check_type":r["check_type"],"outcome":r.get("outcome"),"basis":r.get("basis"),
                             "source_json":_json(r.get("sources",[])),"raw_json":_json(r.get("raw",r))} for r in request["checks"]]
                for check in checks:
                    check["source_json"] = _json(json.loads(check["source_json"]))
                    check["raw_json"] = _json(json.loads(check["raw_json"]))
                if checks != expected:
                    findings.append(f"{request['record_key']} 核验依据或明细不一致")
        if not preview:
            # Validate every record before writing; all changed inputs and outputs commit together.
            with nullcontext():
                for (stock_id, date), value in resolver.changed_inputs.items():
                    connection.execute("""INSERT INTO research_theme_inputs VALUES(?,?,?,?,?,?)
                        ON CONFLICT(stock_id,first_board_date) DO UPDATE SET main_theme=excluded.main_theme,
                        basis=excluded.basis,sources_json=excluded.sources_json,
                        attribute_overrides_json=excluded.attribute_overrides_json""",
                        (stock_id,date,value["main_theme"],value["basis"],_json(value["sources"]),_json(value["attributes"])))
                for request, fact in zip(requests, facts["records"]):
                    results.append(store.write_research(request, connection=connection))
                    connection.execute("""UPDATE launch_rounds SET first_board_date=? WHERE id=(
                        SELECT e.launch_round_id FROM current_static_research r JOIN first_open_events e
                        ON e.id=r.first_open_event_id WHERE r.legacy_record_key=?)""",
                        (fact["identity"]["first_board_date"],fact["record_key"]))
                for block in blocked:
                    # A changed dependency invalidates old computed fields; expose the exact missing input.
                    request = {"record_key": block["record_key"], "kind": "static", "research_status": "needs_input",
                        "updates": {"补涨判断": None,"压制判断": None,"映射依据": None,"压制依据": None,
                                    "自动推导": True,"自动推导缺项": block["reason"],"静态筛选结论": "待补齐"},
                        "remove_fields": ["首开潜在竞争对手事实清单","首开潜在竞争对手候选全集",
                                          "补涨映射明细","一字压制核验明细"], "checks": []}
                    request["request_id"] = "derive-pending-" + hashlib.sha256(_json(request).encode()).hexdigest()
                    saved_row = _select_records(connection,None,None,[block["record_key"]])[0]
                    try:
                        own = resolver.inputs.get(resolver.round_key(saved_row["stock_id"],saved_row["focus_date"]))
                    except MissingInput:
                        own = None
                    request["confirmation_status"] = saved_row["confirmation_status"]
                    request["updates"].update(pending_inputs.get(block["record_key"],{}))
                    if own:
                        request["updates"].update({"唯一主炒作属性":own["main_theme"],"唯一主炒依据":own["basis"]})
                    raw = dict(json.loads(saved_row["raw_json"]),**request["updates"])
                    if raw.get("公告污染") and own:
                        request["updates"]["公告真实属性"] = own["main_theme"]
                    elif raw.get("公告污染") is False:
                        request["remove_fields"].append("公告真实属性")
                    request["request_id"] = "derive-pending-" + hashlib.sha256(_json({k:v for k,v in request.items() if k != "request_id"}).encode()).hexdigest()
                    results.append(store.write_research(request, connection=connection))
                for key, deps in dependencies.items():
                    connection.execute("DELETE FROM research_dependencies WHERE record_key=?", (key,))
                    connection.executemany("INSERT INTO research_dependencies VALUES(?,?,?)",
                                           [(key,stock,date) for stock,date in sorted(deps)])
                for request in requests:
                    saved = json.loads(connection.execute("SELECT raw_json FROM current_static_research WHERE legacy_record_key=?",
                                                         (request["record_key"],)).fetchone()[0])
                    if any(saved.get(k) != v for k,v in request["updates"].items()) or any(k in saved for k in request["remove_fields"]):
                        raise RuntimeError(f"写后核对失败：{request['record_key']}")
                if facts["records"]:
                    last = max(facts["records"], key=lambda f:(f["identity"]["focus_date"],f["record_key"]))
                    old = connection.execute("SELECT value FROM store_meta WHERE key='research_cursor'").fetchone()
                    old = json.loads(old[0]) if old else {}
                    if (last["identity"]["focus_date"],last["record_key"]) > (old.get("focus_date",""),old.get("record_key","")):
                        cursor = {"year":int(last["identity"]["focus_date"][:4]),"focus_date":last["identity"]["focus_date"],
                                  "record_key":last["record_key"],"batch_id":facts["batch_id"]}
                        connection.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES('research_cursor',?)", (_json(cursor),))
                if any(not r.get("deduplicated") for r in results):
                    connection.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES('static_export_pending','1')")
                if receipt:
                    receipt = dict(receipt)
                    receipt.setdefault("record_keys",sorted(keys))
                    connection.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES(?,?)",
                                       (receipt["key"],_json(receipt)))
            connection.commit()
        else:
            connection.rollback()
        written = time.perf_counter()
        changed = sum(not r.get("deduplicated") for r in results)
        export = store.publish_pending(export_root,publish_root) if publish and not preview else None
        finished = time.perf_counter()
        timing.update({"setup": prepared-started-timing["prepare"]-timing["match"],
                       "write_verify": written-prepared,"export": finished-written,"total": finished-started})
        return {"record_count": len(keys), "complete": len(requests), "blocked": blocked, "changed": changed,"findings":findings,
                "preview": preview, "timing_seconds": {k:round(v,4) for k,v in timing.items()},
                "records": [{"record_key":d["record_key"],"main_theme":d["static"]["main_theme"],
                             "replenishment":d["static"]["replenishment_result"],"suppression":d["static"]["suppression_result"],
                             "competitors":[m["股票代码"] for m in d["static"]["competitors"]]} for d in decisions["records"]],
                "export": {"output_dir": export["output_dir"],"published":export["published"]} if export else None}
    finally:
        connection.close()


def set_theme(store, record_key, theme, basis=None, preview=False):
    connection = store.connect()
    try:
        row = _select_records(connection, None, None, [record_key])[0]
        actual = _actual_first_board_date(connection, row["stock_id"], row["focus_date"])
        edit = {"code":row["code"],"first_board_date":actual,"main_theme":theme}
        if basis:
            edit["basis"] = basis
    finally:
        connection.close()
    return recompute(store, [record_key], {"themes":[edit]}, preview=preview)

