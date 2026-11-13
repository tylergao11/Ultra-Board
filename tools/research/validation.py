"""Read-only acceptance of current facts, record identities and published views."""
from __future__ import annotations

import json
import time

from .system import canonical_hash, collect_sources, json_text, sha256_file


def _paths(document):
    return {v.split("（",1)[0].strip() for v in collect_sources(document)
            if v.startswith(("data/","docs/","tools/"))}


def verify_store(store, directory):
    started = time.perf_counter()
    findings = []
    current_paths = set()
    connection = store.connect()
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = [tuple(r) for r in connection.execute("PRAGMA foreign_key_check")]
        if integrity!="ok" or foreign_keys:
            findings.append({"kind":"database_integrity","result":integrity,"foreign_keys":foreign_keys})
        counts = {name:connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in (
            "stocks","source_records","legacy_key_map","current_static_research","current_dynamic_research",
            "research_theme_inputs","research_dependencies")}
        if counts["legacy_key_map"]!=counts["current_static_research"]:
            findings.append({"kind":"record_mapping_count"})
        for row in connection.execute("SELECT id,source_kind,record_key,raw_json,raw_sha256 FROM source_records"):
            raw = json.loads(row["raw_json"])
            if canonical_hash(raw)!=row["raw_sha256"]:
                findings.append({"kind":"record_identity_changed","id":row["id"],"record_key":row["record_key"]})
            if raw or row['source_kind'] not in {'record_anchor','announcement_anchor'}:
                findings.append({'kind':'duplicate_research_payload','record_key':row['record_key']})
        for table in ('field_mappings','archived_sections','revisions'):
            if connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]:
                findings.append({'kind':'obsolete_research_copy','table':table})
        for row in connection.execute("""SELECT m.legacy_record_key FROM legacy_key_map m
            LEFT JOIN source_records s ON s.id=m.static_source_record_id
            LEFT JOIN current_static_research r ON r.legacy_record_key=m.legacy_record_key
            WHERE s.id IS NULL OR r.id IS NULL OR r.source_record_id<>s.id"""):
            findings.append({"kind":"source_mapping","record_key":row[0]})
        duplicate_counts = {}
        for table,keys in (("stocks","code"),("current_static_research","legacy_record_key"),
                           ("current_dynamic_research","first_open_event_id,plan_id")):
            duplicate_counts[table] = connection.execute(f"SELECT COUNT(*) FROM (SELECT {keys} FROM {table} GROUP BY {keys} HAVING COUNT(*)>1)").fetchone()[0]
        if any(duplicate_counts.values()):
            findings.append({"kind":"duplicate_current_identity","counts":duplicate_counts})
        static = {}
        fields = {"唯一主炒作属性":"main_theme","补涨判断":"replenishment_result","压制判断":"suppression_result",
                  "公告污染":"announcement_pollution"}
        for row in connection.execute("SELECT * FROM current_static_research"):
            raw = json.loads(row["raw_json"])
            current_paths.update(_paths(raw))
            current_paths.update(_paths({"来源":json.loads(row["evidence_snapshot_json"])}))
            for field,column in fields.items():
                if field in raw and raw[field]!=row[column]:
                    findings.append({"kind":"current_column","record_key":row["legacy_record_key"],"field":field})
            static[row["legacy_record_key"]] = (row,raw)
        dynamic = {}
        for row in connection.execute("""SELECT d.*,p.name AS plan_name FROM current_dynamic_research d
            JOIN research_plans p ON p.id=d.plan_id"""):
            raw = json.loads(row["raw_json"])
            current_paths.update(_paths(raw))
            current_paths.update(_paths({"来源":json.loads(row["evidence_snapshot_json"])}))
            dynamic[(row["legacy_record_key"],row["plan_name"])] = row
        out_of_sync = []
        for kind,path in (("static",store.root/"data/store/rules/static_rules.json"),
                          ("dynamic",store.root/"data/store/rules/dynamic_rules.json"),("workflow",store.root/"AGENTS.md")):
            row = connection.execute("SELECT source_sha256 FROM rule_sets WHERE rule_type=? AND status='current'",(kind,)).fetchone()
            if not row or sha256_file(path)!=row[0]:
                out_of_sync.append(kind)
        if out_of_sync:
            findings.append({"kind":"rules_not_synced","rules":out_of_sync})
        automatic_keys = [key for key,(_,raw) in static.items() if raw.get("自动推导")]
    finally:
        connection.close()
    source_gaps = sorted(p for p in current_paths if not (store.root/p).exists())
    if source_gaps:
        findings.append({"kind":"current_source_missing","paths":source_gaps})
    from .derive import recompute
    automatic = recompute(store,automatic_keys,preview=True,verify_saved=True) if automatic_keys and not out_of_sync else {"complete":0,"findings":[],"blocked":[]}
    if automatic["findings"] or automatic["blocked"]:
        findings.append({"kind":"automatic_research","findings":automatic["findings"],"pending":automatic["blocked"]})
    publication = {"checked":False}
    if store.db_path==store.root/"data/store/research.sqlite":
        try:
            pointer = json.loads((store.root/"data/store/exports/current.json").read_text(encoding="utf-8"))
            manifest_path = store.root/pointer["manifest"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for item in manifest["files"]:
                path = manifest_path.parent/item["name"]
                if not path.is_file() or path.stat().st_size!=item["size"] or sha256_file(path)!=item["sha256"]:
                    findings.append({"kind":"export_checksum","file":str(path)})
                if item["name"] in ("一字首开研究总表.json","一字首开买卖研究表.json") and sha256_file(store.root/item["name"])!=item["sha256"]:
                    findings.append({"kind":"root_publication","file":item["name"]})
            shown = json.loads((store.root/"一字首开研究总表.json").read_text(encoding="utf-8"))["一字首开股票与数据"]
            if len(shown)!=len(static) or len({r["记录键"] for r in shown})!=len(static):
                findings.append({"kind":"static_display_count"})
            for item in shown:
                row,raw = static[item["记录键"]]
                expected = {"唯一主炒":row["main_theme"],"补涨判断":row["replenishment_result"],"压制判断":row["suppression_result"],
                    "公告污染":None if row["announcement_pollution"] is None else bool(row["announcement_pollution"]),
                    "静态筛选结论":raw.get("静态筛选结论"),"潜在竞争对手":raw.get("首开潜在竞争对手事实清单"),"待补齐":raw.get("自动推导缺项")}
                if any(item.get(k)!=v for k,v in expected.items()):
                    findings.append({"kind":"static_display_value","record_key":item["记录键"]})
            shown = json.loads((store.root/"一字首开买卖研究表.json").read_text(encoding="utf-8"))["买卖研究记录"]
            if len(shown)!=len(dynamic) or len({(r["记录键"],r["方案"]) for r in shown})!=len(dynamic):
                findings.append({"kind":"dynamic_display_count"})
            for item in shown:
                row = dynamic[(item["记录键"],item["方案"])]
                expected = {"竞价结果":row["auction_result"],"卡位结果":row["pk_result"],"买点结果":row["buy_result"],
                    "买入价格":None if row["buy_price_milli"] is None else row["buy_price_milli"]/1000,
                    "盈亏百分比":None if row["return_pct_micros"] is None else row["return_pct_micros"]/1_000_000}
                if any(item.get(k)!=v for k,v in expected.items()):
                    findings.append({"kind":"dynamic_display_value","record_key":item["记录键"]})
            publication = {"checked":True,"generation_key":manifest["generation_key"],"files":len(manifest["files"])}
        except (OSError,KeyError,ValueError) as exc:
            findings.append({"kind":"publication_read","error":str(exc)})
    result = {"passed":not findings,"scope":"current library, unique research inputs, evidence references and published output",
              "counts":counts,"integrity_check":integrity,"foreign_key_errors":len(foreign_keys),"findings":findings,
              "automatic_records":automatic["complete"],
              "publication":publication,"elapsed_seconds":round(time.perf_counter()-started,3)}
    directory.mkdir(parents=True,exist_ok=True)
    (directory/"verification.json").write_text(json_text(result,pretty=True)+"\n",encoding="utf-8")
    return result
