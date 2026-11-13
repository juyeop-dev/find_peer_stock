from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_stock_information_2015 as config
import backfill_stock_information_2024_h2 as recovery
from backfill_sec_financials_2015 import frame_fact
from backfill_yahoo_calendars import requested_dates


class Historical2015Tests(unittest.TestCase):
    def test_actual_2015_quarters_survive_and_later_statements_are_unchanged(self):
        names = ["START", "END", "STATE", "AUDIT", "TABLE", "COVERAGE_KEY", "FETCHED_KEY", "RESUME"]
        with patch.multiple(recovery, **{name: getattr(recovery, name) for name in names}), patch.object(recovery.info, "START", recovery.info.START):
            config.configure()
            payload = {"timeseries": {"result": [{"meta": {"symbol": ["TEST"]},
                "quarterlyTotalRevenue": [{"asOfDate": "2015-03-31", "periodType": "3M", "currencyCode": "USD", "reportedValue": {"raw": 0}}],
                "quarterlyOperatingIncome": [{"asOfDate": "2015-03-31", "periodType": "3M", "currencyCode": "USD", "reportedValue": {"raw": -7}}]}]}}
            rows = recovery.info.parse_yahoo_financials(payload, "TEST", "2015-12-31")
            self.assertEqual(len(rows), 1)
            later = {"type": "annual", "period_end": "2016-12-31", "currency": "USD", "source": "original", "revenue": 12}
            value = recovery.merge({"financials": [later]}, rows, "2026-11-13T00:00:00Z")
            self.assertIn(later, value["financials"])
            self.assertEqual(value["financials"][0]["revenue"], 0)
            self.assertEqual(value["financials"][0]["operating_income"], -7)
            self.assertEqual(value["historical_2015_coverage"]["quarterly_periods"], 1)

    def test_sec_uses_actual_periods_without_turning_cumulative_values_into_quarters(self):
        def fact(start, end):
            return {"start": start, "end": end, "val": -1, "cik": 320193, "accn": "0000320193-15-000001"}
        self.assertEqual(frame_fact(fact("2015-01-01", "2015-03-31"), False)["value"], -1)
        self.assertIsNone(frame_fact(fact("2015-01-01", "2015-06-30"), False))
        self.assertIsNone(frame_fact(fact("2016-01-01", "2016-03-31"), False))

    def test_calendar_keeps_extraordinary_closures_and_has_no_invented_saturday_sessions(self):
        expected = {"korea": 248, "us": 252, "japan": 244, "china": 244, "taiwan": 244, "europe": 257}
        sessions = {market: requested_dates(date(2015, 1, 1), date(2015, 12, 31), market) for market in expected}
        self.assertEqual({market: len(days) for market, days in sessions.items()}, expected)
        self.assertNotIn(date(2015, 8, 14), sessions["korea"])
        self.assertNotIn(date(2015, 9, 3), sessions["china"])
        self.assertNotIn(date(2015, 9, 4), sessions["china"])
        for day in [date(2015, 7, 10), date(2015, 9, 29)]:
            self.assertNotIn(day, sessions["taiwan"])
        self.assertTrue(all(day.weekday() < 5 for day in sessions["taiwan"]))


if __name__ == "__main__":
    unittest.main()
