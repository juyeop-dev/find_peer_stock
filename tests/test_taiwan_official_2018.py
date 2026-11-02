import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from backfill_yahoo_calendars import Bar
from recover_taiwan_official_2018 import verified_factor


class OfficialSaturdayBasisTests(unittest.TestCase):
    def setUp(self):
        self.before = Bar(date(2018, 3, 30), 100, 110, 90, 105, 1000)
        self.after = Bar(date(2018, 4, 2), 105, 115, 95, 110, 2000)
        self.scaled = [Bar(b.day, b.open/2, b.high/2, b.low/2, b.close/2, b.volume*2) for b in [self.before,self.after]]

    def test_all_ohlc_on_both_sides_must_verify_one_observed_split_factor(self):
        self.assertEqual(verified_factor(self.before, self.after, self.scaled), .5)
        bad = [self.scaled[0], Bar(self.after.day, 105, 115, 95, 110, 2000)]
        with self.assertRaises(ValueError):
            verified_factor(self.before, self.after, bad)
        bad = [self.scaled[0], Bar(self.after.day, 52.5, 58, 47.5, 55, 4000)]
        with self.assertRaises(ValueError):
            verified_factor(self.before, self.after, bad)

    def test_a_missing_neighbor_cannot_be_filled_or_verified_with_one_close(self):
        with self.assertRaises(ValueError):
            verified_factor(self.before, self.after, self.scaled[:1])
