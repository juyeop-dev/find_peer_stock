from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from backfill_sector_history_2024 import eligible_on_day


class HistoricalEligibilityTests(unittest.TestCase):
    def test_unknown_dates_stay_in_coverage_and_verified_later_listings_are_excluded(self):
        stock={'ticker':'TEST.KS'};day=date(2020,1,2)
        self.assertTrue(eligible_on_day(stock,{}, {},day))
        self.assertTrue(eligible_on_day(stock,{}, {'TEST.KS':'2019-01-01'},day))
        self.assertFalse(eligible_on_day(stock,{}, {'TEST.KS':'2021-01-01'},day))

    def test_observed_prices_prevent_incorrect_listing_dates_from_hiding_gaps(self):
        self.assertTrue(eligible_on_day({'ticker':'TEST.KS'}, {date(2019,12,30):[]}, {'TEST.KS':'2021-01-01'}, date(2020,1,2)))


if __name__=='__main__': unittest.main()
