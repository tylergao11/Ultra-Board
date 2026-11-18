"""Evaluate the current unified list at the first post-buy broken close."""
import hashlib
import json
from decimal import Decimal
from statistics import median
from .batch import _trade_market


def exit_quote(market):
    for quote in market['following']:
        if quote['day'] <= market['event_date']:
            raise ValueError('T+1 violation')
        if quote.get('close') is None or quote.get('limit_up') is None:
            raise ValueError(f"Missing close or limit price: {quote['day']}")
        if quote['close'] != quote['limit_up']:
            return quote
    raise ValueError('No observed broken close after buy')


def evaluate(store, commit=False):
    c = store.connect()
    records = []
    saved_outcomes = {}
    try:
        for row in c.execute('SELECT * FROM current_dynamic_research').fetchall():
            raw = json.loads(row['raw_json'])
            if not raw.get('当前统一交易清单'):
                continue
            key = row['legacy_record_key']
            saved_outcomes[key] = dict(raw.get('买入后结果') or {})
            buy = raw['首开买点']
            if buy.get('是否买入') is not True:
                raise ValueError(f'{key}: current list contains a non-buy')
            sid = c.execute('SELECT id FROM stocks WHERE code=?', (key[:6],)).fetchone()[0]
            market = _trade_market(c, sid, buy['买入日期'], 100)
            event = market['event']
            price = buy.get('买入价格') or event.get('limit_up')
            if not price or price != event.get('limit_up'):
                raise ValueError(f'{key}: buy price not verified at limit')
            sold = dict(exit_quote(market), exit_reason='断板日尾盘卖出')
            sold['exit_price'] = sold['close']
            pct = (Decimal(str(sold['exit_price'])) / Decimal(str(price)) - 1) * 100
            name = json.loads(c.execute('SELECT raw_json FROM current_static_research WHERE legacy_record_key=?', (key,)).fetchone()[0])['股票']
            trail = [q for q in market['following'] if q['day'] <= sold['day']]
            records.append({'记录键': key, '股票': name, '买入日期': buy['买入日期'],
                            '买入价格': price, '卖出日期': sold['day'], '卖出价格': sold['exit_price'],
                            '卖出原因':sold['exit_reason'],
                            '收益率': float(pct), '持有交易日数': len(trail),
                            '核验日线': [{k:q.get(k) for k in ('day','open','previous_close','close','limit_up','sources')} for q in trail],
                            '买入来源': event['sources']})
        if not records:
            raise ValueError('Current unified list is empty')
        values = [r['收益率'] for r in records]
        wins = [v for v in values if v > 0]
        losses = [v for v in values if v < 0]
        avg_win = sum(wins)/len(wins) if wins else 0
        avg_loss = sum(losses)/len(losses) if losses else 0
        summary = {'笔数':len(values), '盈利笔数':len(wins), '亏损笔数':len(losses),
                   '持平笔数':sum(v==0 for v in values), '胜率':len(wins)/len(values)*100,
                   '平均收益率':sum(values)/len(values), '收益率中位数':median(values),
                   '盈利笔平均收益率':avg_win, '亏损笔平均收益率':avg_loss,
                   '平均盈亏比':avg_win/abs(avg_loss) if losses else None,
                   '最大收益率':max(values), '最小收益率':min(values),
                   '收益分布': {'亏损10%以上':sum(v < -10 for v in values),
                              '亏损0至10%':sum(-10 <= v < 0 for v in values),
                              '持平':sum(v == 0 for v in values),
                              '盈利0至10%':sum(0 < v <= 10 for v in values),
                              '盈利10至30%':sum(10 < v <= 30 for v in values),
                              '盈利30%以上':sum(v > 30 for v in values)}}
        if commit:
            with store.immediate(c):
                for item in records:
                    updates = {'卖出核验':item, '买入后结果':{**saved_outcomes[item['记录键']],
                        '买入价格':item['买入价格'], '卖出日期':item['卖出日期'],
                        '卖出价格':item['卖出价格'], '收益率':item['收益率'],
                        '卖出原因':item['卖出原因']}}
                    digest = hashlib.sha256(json.dumps(updates,sort_keys=True).encode()).hexdigest()
                    store.write_research({'request_id':'tail-close-'+digest,'record_key':item['记录键'],
                                          'kind':'dynamic','confirmation_status':'user_confirmed','updates':updates},c)
                for item in records:
                    saved = json.loads(c.execute('SELECT raw_json FROM current_dynamic_research WHERE legacy_record_key=?', (item['记录键'],)).fetchone()[0])
                    if saved['卖出核验'] != item:
                        raise RuntimeError('Saved result mismatch')
            store.export_all(publish_root=True)
        summary['尾盘卖出笔数'] = len(records)
        return {'口径':'买入次日起，首次收盘未涨停的交易日按收盘价卖出。价格测算不含费用及滑点，不模拟成交排队；逐笔等权，不作账户复利。',
                '统计':summary, '记录':sorted(records,key=lambda r:(r['买入日期'],r['记录键']))}
    finally:
        c.close()
