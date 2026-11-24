"""Decision-boundary tests for buy-day-only research."""
import unittest
from datetime import datetime
from .buy_seal import observe, morning_buy, within_reseal_window, trading_gap_seconds, has_prior_one_word_break
from .system import SHANGHAI


def stamp(t):
    return int(datetime.fromisoformat('2026-02-03T'+t).replace(tzinfo=SHANGHAI).timestamp()*1000)


def market(opening=10, low=9, close=10, starts=('09:30:00',), breaks=(None,)):
    intervals=[{'time':stamp(s),'openTime':stamp(b) if b else None} for s,b in zip(starts,breaks)]
    return {'event_date':'2026-02-03','event':{'open':opening,'high':10,'low':low,'close':close,'limit_up':10,
        'events':[{'event_type':'limit_summary','value':{'board_count':len(starts),'complete':True}},
                  {'event_type':'limit_intervals','value':{'intervals':intervals}}]}}


class BuySealTests(unittest.TestCase):
    def test_current_rule_accepts_non_yizi_within_10m_even_if_failed_close(self):
        o=observe(market(opening=9,close=9,starts=('09:39:30',),breaks=('09:41:00',)))
        self.assertTrue(within_reseal_window(o)[0])
        o_late=observe(market(opening=9,close=9,starts=('09:40:01',),breaks=('09:45:00',)))
        self.assertFalse(within_reseal_window(o_late)[0])

    def test_current_rule_accepts_afternoon_and_cross_lunch_within_10m(self):
        # Afternoon break & reseal within 10 trading minutes
        o_pm=observe(market(starts=('09:30:00','14:23:09'),breaks=('14:22:34',None)))
        self.assertTrue(within_reseal_window(o_pm)[0])
        # Afternoon break & reseal over 10 trading minutes
        o_pm_late=observe(market(starts=('09:30:00','14:15:00'),breaks=('14:00:00',None)))
        self.assertFalse(within_reseal_window(o_pm_late)[0])
        # Cross-lunch 11:25 -> 13:04 = 9 trading minutes (accepted)
        o_lunch_ok=observe(market(starts=('09:30:00','13:04:00'),breaks=('11:25:00',None)))
        self.assertEqual(trading_gap_seconds(o_lunch_ok['broken'], o_lunch_ok['time']), 540.0)
        self.assertTrue(within_reseal_window(o_lunch_ok)[0])
        # Cross-lunch 11:25 -> 13:06 = 11 trading minutes (rejected)
        o_lunch_late=observe(market(starts=('09:30:00','13:06:00'),breaks=('11:25:00',None)))
        self.assertEqual(trading_gap_seconds(o_lunch_late['broken'], o_lunch_late['time']), 660.0)
        self.assertFalse(within_reseal_window(o_lunch_late)[0])
        # Morning break 10:00 -> afternoon reseal 13:01 = 91 trading minutes (rejected)
        o_long=observe(market(starts=('09:30:00','13:01:00'),breaks=('10:00:00',None)))
        self.assertFalse(within_reseal_window(o_long)[0])

    def test_current_rule_does_not_guess_missing_time(self):
        o=observe(market(opening=9));o['time']=None
        self.assertIsNone(morning_buy(o)[0])

    def test_missing_reseal_time_stays_unknown_even_after_noon(self):
        self.assertIsNone(within_reseal_window(dict(buy=True,one=True,time=None,broken=46800,reason=None))[0])

    def test_verified_window_does_not_invent_timestamp(self):
        o=dict(buy=True,one=True,time=None,broken=34203,time_window=[34203,34700],reason=None)
        self.assertTrue(within_reseal_window(o)[0])
        self.assertIsNone(o['time'])
        o['time_window']=[34203,35400]
        self.assertIsNone(within_reseal_window(o)[0])
        o['time_window']=[35000,35400]
        self.assertFalse(within_reseal_window(o)[0])

    def test_actual_seal_interval_overrides_earlier_touch(self):
        m=market(opening=9,starts=('13:01:00',))
        m['event']['events'].append({'event_type':'first_touch','event_time':'09:35:00'})
        self.assertFalse(within_reseal_window(observe(m))[0])

    def test_current_rule_keeps_capital_events_separate(self):
        from .batch import _dynamic_updates
        from .buy_seal import passed
        d=dict(auction={},pk_checks=[],pk_result='不参与筛选',buy_point={},outcome={})
        s=dict(announcement_pollution=True,main_theme='芯片',replenishment_result='先锋',suppression_result='非压制')
        self.assertEqual(_dynamic_updates(True,s,d,{})['买入筛选']['结果'],'通过')
        s['replenishment_result']='补涨'
        self.assertEqual(_dynamic_updates(False,s,d,{})['买入筛选']['结果'],'淘汰')
        self.assertTrue(passed({'补涨判断':'先锋','压制判断':'非压制'}))
        self.assertFalse(passed({'补涨判断':'补涨','压制判断':'非压制'}))
        self.assertFalse(passed({'补涨判断':'蹭股','压制判断':'非压制'}))
        s['main_theme']='医药'
        self.assertEqual(_dynamic_updates(True,s,d,{})['买入筛选']['结果'],'淘汰')
        s['main_theme']='并购重组'
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

    def test_first_one_word_open_sequence_filter(self):
        # Continuous one-word run (一字-一字-一字 -> 首开): allowed
        self.assertFalse(has_prior_one_word_break([1, 1, 1]))
        # Turnover then first one-word run (换手-换手-一字-一字 -> 首开): allowed
        self.assertFalse(has_prior_one_word_break([0, 0, 1, 1]))
        # Turnover -> one-word -> turnover -> second one-word (换手-一字-换手-一字): rejected
        self.assertTrue(has_prior_one_word_break([0, 1, 0, 1]))
        # First-board one-word -> turnover -> second one-word (首板一字-换手-一字): rejected
        self.assertTrue(has_prior_one_word_break([1, 0, 1]))
        self.assertTrue(has_prior_one_word_break([1, 0, 0, 1, 1]))



if __name__=='__main__':unittest.main()
