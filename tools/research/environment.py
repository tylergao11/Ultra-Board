"""Read the five-session market environment from saved Kaipanla evidence."""
from datetime import date
import json
import sqlite3


def sector_top3(store, requested_date):
    date.fromisoformat(requested_date)
    with sqlite3.connect((store.root / 'data/store/research.sqlite').as_uri() + '?mode=ro', uri=True) as connection:
        days = [r[0] for r in connection.execute(
            "SELECT trade_date FROM trading_days WHERE is_trading_day=1 "
            "AND raw_market_coverage=1 AND trade_date<=? ORDER BY trade_date DESC LIMIT 5",
            (requested_date,))]
    if len(days) < 5:
        raise ValueError(f"截至{requested_date}本地已采集交易日只有{len(days)}天")
    result = []
    for day in reversed(days):
        path = store.root / 'data/kaipanla/raw' / day / 'sector_ladder.json'
        document = json.loads(path.read_text(encoding='utf-8'))
        sectors = document['sectors']
        top = sectors[:3]
        result.append({'date': day, 'top3': [s['name'] for s in top]})
    return {'requested_date': requested_date, 'as_of': days[0],
            'days': result}
