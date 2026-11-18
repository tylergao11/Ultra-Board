import unittest
from .afternoon import classify

class AfternoonTests(unittest.TestCase):
    def test_first_open_after_noon_is_out_even_without_reseal_time(self):
        self.assertFalse(classify(True,None,13*3600)[0])
    def test_morning_open_afternoon_reseal_is_out(self):
        self.assertFalse(classify(True,14*3600,10*3600)[0])
    def test_eleven_am_is_kept(self):
        self.assertTrue(classify(False,11*3600,None)[0])
    def test_morning_reseal_is_kept(self):
        self.assertTrue(classify(True,10*3600,9*3600+40*60)[0])
    def test_unknown_time_is_not_passed(self):
        with self.assertRaises(ValueError):classify(True,None,None)
