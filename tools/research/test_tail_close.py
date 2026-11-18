import unittest
from .tail_close import exit_quote


class TailCloseTests(unittest.TestCase):
    def test_low_open_does_not_override_sealed_close(self):
        m={'event_date':'2026-01-05','event':{'close':10},'following':[{'day':'2026-01-06','open':9,'close':11,'limit_up':11},{'day':'2026-01-07','open':12,'close':10.5,'limit_up':12.1}]}
        self.assertEqual(exit_quote(m)['close'],10.5)

    def test_flat_open_keeps_position(self):
        m={'event_date':'2026-01-05','event':{'close':10},'following':[{'day':'2026-01-06','open':10,'close':11,'limit_up':11},{'day':'2026-01-07','open':11.5,'close':10.5,'limit_up':12.1}]}
        self.assertEqual(exit_quote(m)['close'],10.5)

    def test_repeated_low_opens_do_not_close_sealed_position(self):
        m={'event_date':'2026-01-05','event':{'close':10},'following':[{'day':'2026-01-06','open':10.5,'close':11,'limit_up':11},{'day':'2026-01-07','open':10.8,'close':12.1,'limit_up':12.1}]}
        with self.assertRaises(ValueError):exit_quote(m)

    def test_buy_day_cannot_be_exit(self):
        with self.assertRaises(ValueError):
            exit_quote({'event_date':'2026-01-05','following':[{'day':'2026-01-05','close':9,'limit_up':10}]})

    def test_sealed_days_are_held_until_first_break(self):
        first={'day':'2026-01-06','close':11,'limit_up':11}
        broken={'day':'2026-01-07','close':10,'limit_up':12.1}
        later={'day':'2026-01-08','close':11,'limit_up':11}
        self.assertEqual(exit_quote({'event_date':'2026-01-05','following':[first,broken,later]}),broken)

    def test_missing_limit_cannot_be_called_break(self):
        with self.assertRaises(ValueError):
            exit_quote({'event_date':'2026-01-05','following':[{'day':'2026-01-06','close':9}]})

    def test_open_position_is_not_closed_at_last_available_price(self):
        with self.assertRaises(ValueError):
            exit_quote({'event_date':'2026-01-05','following':[{'day':'2026-01-06','close':11,'limit_up':11}]})
