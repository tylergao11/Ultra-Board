"""Complete birth-day high-theme lists, independent of candidate attributes."""
from __future__ import annotations

import json
import time
from datetime import date
from collections import defaultdict

from .batch import (_actual_first_board_date, _high_pool, _select_records,
                    _trading_dates, _source_values)
from .derive import Resolver, _parse_edits, save_theme_inputs
from .system import canonical_hash


def birth_fields(day, members, canonical):
    details = []
    for high in members:
        theme = high.get("confirmed_main_theme")
        if not theme:
            raise ValueError(f"{day} 高标 {high.get('code')} 缺少已确认主炒")
        details.append({"股票代码": high["code"], "股票": high["name"],
                        "身位": high["board_height"], "状态": high["status"],
                        "题材": canonical(theme),
                        "来源": sorted(_source_values(high.get("source")) |
                                     set(high.get("main_theme_sources", [])))})
    return {"补涨题材日期": day,
            "出生当日补涨题材": sorted({v["题材"] for v in details}),
            "出生当日补涨高标": details}


def refresh_birth_themes(store, start, end, preview=False, inputs=None):
    """Refresh only this display fact, preserving all prior static/trade decisions."""
    started = time.perf_counter()
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError("起始日期晚于结束日期")
    store.sync_rules()
    c = store.connect()
    try:
        rules = json.loads((store.root / "data/store/rules/static_rules.json").read_text(encoding="utf-8"))["rules"]
        payload = inputs or {}
        if set(payload) - {"themes"}:
            raise ValueError("此入口只接受共享高标题材 themes")
        edits = _parse_edits(c, payload)
        resolver = Resolver(c, rules, edits)
        for sid, first in edits:
            resolver.theme(sid, first, True)
        dates = _trading_dates(c)
        keys = [r[0] for r in c.execute("""SELECT r.legacy_record_key FROM current_static_research r
            JOIN first_open_events e ON e.id=r.first_open_event_id
            JOIN launch_rounds l ON l.id=e.launch_round_id WHERE l.focus_date BETWEEN ? AND ?
            ORDER BY l.focus_date,r.legacy_record_key""", (start, end))]
        rows = _select_records(c, None, None, keys) if keys else []
        names = defaultdict(set)
        for sid, name in c.execute("SELECT stock_id,name FROM stock_names"):
            names[name].add(sid)
        codes = dict(c.execute("SELECT code,id FROM stocks"))
        historical = defaultdict(dict)
        # Reuse current approved research, including the earlier Chinese field schema.
        for row in c.execute("SELECT raw_json FROM current_static_research"):
            raw = json.loads(row[0])
            for h in raw.get("高标事实池", []):
                code = h.get("code", h.get("股票代码"))
                ids = {codes[code]} if code in codes else names[h.get("name", h.get("股票"))]
                theme = h.get("confirmed_main_theme", h.get("首二唯一主炒属性"))
                sources = sorted(_source_values(h))
                day = raw.get("补涨题材日期") or raw.get("底稿首板日期")
                if len(ids) != 1 or not theme or not day:
                    continue
                sid = next(iter(ids))
                first = _actual_first_board_date(c, sid, day)
                if first:
                    historical[(sid, first)].setdefault(resolver.canonical(theme), sources)
        pools, changes, missing = {}, [], []
        for row in rows:
            day = _actual_first_board_date(c, row["stock_id"], row["focus_date"])
            if not day:
                missing.append({"record_key": row["legacy_record_key"], "reason": "缺少实际首板日"})
                continue
            if day not in pools:
                pool = _high_pool(c, dates, day, None, rules["补涨时间参数"])
                errors = []
                for h in pool["members"]:
                    first = _actual_first_board_date(c, h["stock_id"], day)
                    saved = resolver.inputs.get((h["stock_id"], first))
                    old = historical.get((h["stock_id"], first), {})
                    if saved:
                        h["confirmed_main_theme"] = saved["main_theme"]
                        h["main_theme_sources"] = saved["sources"]
                    elif len(old) == 1:
                        h["confirmed_main_theme"] = next(iter(old))
                        h["main_theme_sources"] = next(iter(old.values()))
                    elif not h.get("confirmed_main_theme"):
                        errors.append({"code": h["code"], "name": h["name"], "first_board_date": first,
                                       "existing_themes": sorted(old), "first_two": h["first_two"]})
                pools[day] = (pool, errors)
            pool, errors = pools[day]
            if errors:
                missing.append({"record_key": row["legacy_record_key"], "date": day, "highs": errors})
                continue
            updates = birth_fields(day, pool["members"], resolver.canonical)
            changes.append((row, updates))
        # Never publish a partial range as complete.
        if missing or preview:
            return {"record_count": len(rows), "complete": len(changes), "missing": missing,
                    "preview": preview, "elapsed_seconds": round(time.perf_counter()-started, 3)}
        changed = 0
        corrected_dates = []
        display_stale = False
        if store.db_path == store.root / "data/store/research.sqlite":
            try:
                shown = {r["记录键"]: r for r in json.loads(
                    (store.root / "一字首开研究总表.json").read_text(encoding="utf-8"))["一字首开股票与数据"]}
                display_stale = any(any(shown.get(row["legacy_record_key"], {}).get(k) != updates[k]
                    for k in ("补涨题材日期", "出生当日补涨题材")) for row, updates in changes)
            except (OSError, ValueError, KeyError):
                display_stale = True
        with store.immediate(c):
            save_theme_inputs(c, resolver.changed_inputs)
            for row, updates in changes:
                raw = json.loads(row["raw_json"])
                if row["first_board_date"] != updates["补涨题材日期"]:
                    c.execute("UPDATE launch_rounds SET first_board_date=? WHERE id=?",
                              (updates["补涨题材日期"], row["launch_round_id"]))
                    corrected_dates.append({"record_key": row["legacy_record_key"],
                        "before": row["first_board_date"], "after": updates["补涨题材日期"]})
                if all(raw.get(k) == v for k, v in updates.items()):
                    continue
                request = {"kind": "static", "record_key": row["legacy_record_key"],
                           "expected_version": row["version"], "updates": updates,
                           "research_status": row["research_status"],
                           "confirmation_status": row["confirmation_status"]}
                request["request_id"] = "birth-themes-" + canonical_hash(request)
                store.write_research(request, c)
                changed += 1
            if changed or display_stale or corrected_dates:
                c.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES('static_export_pending','1')")
        publication = store.publish_pending()
        return {"record_count": len(rows), "complete": len(changes), "changed": changed,
                "corrected_dates": corrected_dates, "missing": [], "export": publication,
                "elapsed_seconds": round(time.perf_counter()-started, 3)}
    finally:
        c.close()
