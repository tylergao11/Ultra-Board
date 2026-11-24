import unittest
from .afternoon import classify

class AfternoonTests(unittest.TestCase):
    def test_unknown_reseal_time_raises_even_after_noon(self):
        with self.assertRaises(ValueError):classify(True,None,13*3600)
    def test_reseal_over_10_trading_minutes_is_out(self):
        self.assertFalse(classify(True,14*3600,10*3600)[0])
    def test_non_yizi_after_0940_is_out(self):
        self.assertFalse(classify(False,11*3600,None)[0])
    def test_non_yizi_within_10m_is_kept(self):
        self.assertTrue(classify(False,9*3600+39*60,None)[0])
    def test_cross_lunch_within_10_trading_minutes_is_kept(self):
        self.assertTrue(classify(True,13*3600+4*60,11*3600+25*60)[0])
    def test_afternoon_within_10m_is_kept(self):
        self.assertTrue(classify(True,14*3600+23*60,14*3600+22*60)[0])
    def test_unknown_time_is_not_passed(self):
        with self.assertRaises(ValueError):classify(True,None,None)
