"""Independent read-only audit against downloaded daily limit pools and exports."""
import ast
import bisect
import csv
import hashlib
import json


def audit_birth_themes(store, start, end):
    c = store.connect()
    try:
        rules = json.loads((store.root / 'data/store/rules/static_rules.json').read_text(encoding='utf-8'))['rules']
        aliases = rules['自动匹配']['属性归并']
        def canonical(theme):
            seen = set()
            while theme in aliases and aliases[theme] != theme:
                if theme in seen:
                    raise ValueError('题材归并循环')
                seen.add(theme)
                theme = aliases[theme]
            return theme
        days = [r[0] for r in c.execute("SELECT DISTINCT trade_date FROM daily_market WHERE source_type='kaipanla_limit_pool' ORDER BY trade_date")]
        cache = {}
        def pool(day):
            if day not in cache:
                raw = json.loads((store.root / 'data/kaipanla/raw' / day / 'zt_pool.json').read_text(encoding='utf-8'))
                cache[day] = {r['code']: r for r in raw['stocks']}
            return cache[day]
        pointer = json.loads((store.root / 'data/store/exports/current.json').read_text(encoding='utf-8'))
        manifest_path = store.root / pointer['manifest']
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        issues = []
        for item in manifest['files']:
            data = (manifest_path.parent / item['name']).read_bytes()
            if len(data) != item['size'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                issues.append({'kind': '导出文件校验失败', 'file': item['name']})
        shown = {r['记录键']: r for r in json.loads((store.root / '一字首开研究总表.json').read_text(encoding='utf-8'))['一字首开股票与数据']}
        with (manifest_path.parent / '一字首开研究总表.csv').open(encoding='utf-8-sig', newline='') as f:
            csv_rows = {r['记录键']: r for r in csv.DictReader(f)}
        rows = c.execute('''SELECT r.legacy_record_key,r.raw_json,l.first_board_date FROM current_static_research r
            JOIN first_open_events e ON e.id=r.first_open_event_id JOIN launch_rounds l ON l.id=e.launch_round_id
            WHERE l.focus_date BETWEEN ? AND ?''', (start, end)).fetchall()
        no_highs = 0
        for row in rows:
            key = row['legacy_record_key']
            raw = json.loads(row['raw_json'])
            day, themes, highs = (raw.get(k) for k in ('补涨题材日期','出生当日补涨题材','出生当日补涨高标'))
            if day is None or not isinstance(themes,list) or not isinstance(highs,list):
                issues.append({'record_key':key,'kind':'字段不完整'})
                continue
            if day != row['first_board_date']:
                issues.append({'record_key':key,'kind':'首板日期不一致'})
            current = pool(day)
            index = bisect.bisect_left(days,day)
            previous = pool(days[index-1]) if index else {}
            expected = {code for code,r in current.items() if r['boards'] >= rules['补涨时间参数']['前序最低连续板数']}
            expected |= {code for code,r in previous.items() if code not in current and r['boards'] >= rules['补涨时间参数']['当日断板前最低连续板数']}
            actual = {h['股票代码'] for h in highs}
            if actual != expected or len(actual) != len(highs):
                issues.append({'record_key':key,'kind':'高标范围错误','missing':sorted(expected-actual),'extra':sorted(actual-expected)})
            if themes != sorted({canonical(h['题材']) for h in highs}):
                issues.append({'record_key':key,'kind':'题材归并去重错误'})
            for field in ('补涨题材日期','出生当日补涨题材'):
                if shown.get(key,{}).get(field) != raw[field]:
                    issues.append({'record_key':key,'kind':'JSON与数据库不一致','field':field})
            try:
                if ast.literal_eval(csv_rows[key]['出生当日补涨题材']) != themes or csv_rows[key]['补涨题材日期'] != day:
                    issues.append({'record_key':key,'kind':'CSV与数据库不一致'})
            except (KeyError, ValueError, SyntaxError):
                issues.append({'record_key':key,'kind':'CSV内容无效'})
            if not themes:
                no_highs += 1
        integrity = c.execute('PRAGMA integrity_check').fetchone()[0]
        foreign_keys = c.execute('PRAGMA foreign_key_check').fetchall()
        if integrity != 'ok' or foreign_keys:
            issues.append({'kind':'数据库完整性错误'})
        return {'passed':not issues,'from_date':start,'to_date':end,'record_count':len(rows),
                'no_eligible_highs':no_highs,'findings':issues,'integrity_check':integrity}
    finally:
        c.close()
