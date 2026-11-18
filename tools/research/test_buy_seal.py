"""Decision-boundary tests for buy-day-only research."""
import unittest
from datetime import datetime
from .buy_seal import observe, morning_buy
from .system import SHANGHAI


def stamp(t):
    return int(datetime.fromisoformat('2026-02-03T'+t).replace(tzinfo=SHANGHAI).timestamp()*1000)


def market(opening=10, low=9, close=10, starts=('09:30:00',), breaks=(None,)):
    intervals=[{'time':stamp(s),'openTime':stamp(b) if b else None} for s,b in zip(starts,breaks)]
    return {'event_date':'2026-02-03','event':{'open':opening,'high':10,'low':low,'close':close,'limit_up':10,
        'events':[{'event_type':'limit_summary','value':{'board_count':len(starts),'complete':True}},
                  {'event_type':'limit_intervals','value':{'intervals':intervals}}]}}


class BuySealTests(unittest.TestCase):
    def test_current_rule_accepts_morning_failed_close(self):
        o=observe(market(opening=9,close=9,starts=('11:00:00',),breaks=('11:01:00',)))
        self.assertTrue(morning_buy(o)[0])

    def test_current_rule_rejects_afternoon_reseal(self):
        o=observe(market(starts=('09:30:00','13:01:00'),breaks=('10:00:00',None)))
        self.assertFalse(morning_buy(o)[0])

    def test_current_rule_does_not_guess_missing_time(self):
        o=observe(market(opening=9));o['time']=None
        self.assertIsNone(morning_buy(o)[0])

    def test_afternoon_first_break_rejects_even_without_reseal_time(self):
        self.assertFalse(morning_buy(dict(buy=True,one=True,time=None,broken=46800,reason=None))[0])

    def test_verified_morning_window_does_not_invent_timestamp(self):
        o=dict(buy=True,one=True,time=None,broken=34203,time_window=[34203,41400],reason=None)
        self.assertTrue(morning_buy(o)[0])
        self.assertIsNone(o['time'])
        o['time_window']=[34203,46800]
        self.assertIsNone(morning_buy(o)[0])

    def test_actual_seal_interval_overrides_earlier_touch(self):
        m=market(opening=9,starts=('13:01:00',))
        m['event']['events'].append({'event_type':'first_touch','event_time':'10:00:00'})
        self.assertFalse(morning_buy(observe(m))[0])

    def test_current_rule_keeps_capital_events_separate(self):
        from .batch import _dynamic_updates
        d=dict(auction={},pk_checks=[],pk_result='不参与筛选',buy_point={},outcome={})
        s=dict(announcement_pollution=True,main_theme='芯片')
        self.assertEqual(_dynamic_updates(True,s,d,{})['买入筛选']['结果'],'通过')
        s['main_theme']='医药'
        self.assertEqual(_dynamic_updates(True,s,d,{})['买入筛选']['结果'],'淘汰')

    def test_sealed_close_proves_buy_without_board_count(self):
        m=market(opening=9)
        m['event']['events']=[]
        x=observe(m)
        self.assertTrue(x['buy'])
        self.assertIsNone(x['time'])

    def test_unsealed_touch_without_count_stays_unknown(self):
        m=market(opening=9,close=9)
        m['event']['events']=[]
        self.assertIsNone(observe(m)['buy'])

    def test_first_recorded_seal_after_open_is_first_reseal(self):
        x=observe(market(starts=('09:32:00','09:43:00'),breaks=('09:42:00',None)))
        self.assertEqual(x['time'],34320)
        self.assertIsNone(x['broken'])

    def test_failed_close_does_not_cancel_buy(self):
        x=observe(market(close=9,starts=('09:30:00','09:40:00'),breaks=('09:35:00','10:00:00')))
        self.assertTrue(x['buy']);self.assertFalse(x['sealed'])

    def test_no_reseal_is_not_buy(self):
        self.assertFalse(observe(market(close=9,breaks=('09:35:00',)))['buy'])

    def test_observation_retains_afternoon_event_as_fact(self):
        self.assertTrue(observe(market(opening=9,starts=('10:00:00',)))['buy'])
        self.assertTrue(observe(market(opening=9,starts=('14:00:00',)))['buy'])
        self.assertTrue(observe(market(opening=9,starts=('09:59:59',)))['buy'])

    def test_observation_retains_afternoon_reseal_as_fact(self):
        self.assertTrue(observe(market(starts=('09:30:00','13:01:00'),breaks=('13:00:00',None)))['buy'])



if __name__=='__main__':unittest.main()
