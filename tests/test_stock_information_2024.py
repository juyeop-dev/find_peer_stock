from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_stock_information_2024 as whole
import backfill_stock_information_2024_h2 as recovery
import stock_information as info


class WholeYearFinancialTests(unittest.TestCase):
    def test_full_year_has_independent_scope_and_retains_later_reports(self):
        names = ["START", "STATE", "AUDIT", "TABLE", "COVERAGE_KEY", "FETCHED_KEY", "RESUME"]
        with patch.multiple(recovery, **{name: getattr(recovery, name) for name in names}):
            whole.configure()
            original = {"financials": [{"type": "annual", "period_end": "2025-06-30", "currency": "USD", "source": "original", "revenue": 50}]}
            result = recovery.merge(original, [{"type": "annual", "period_end": "2024-06-30", "currency": "USD", "source": "reported", "revenue": 0, "operating_income": -5}], "2026-10-26T00:00:00Z")
            self.assertEqual(recovery.TABLE, "financial_2024_updates")
            self.assertEqual(result["historical_2024_coverage"]["start"], "2024-01-01")
            self.assertEqual(result["financials"][0]["revenue"], 0)
            self.assertEqual(result["financials"][-1]["period_end"], "2025-06-30")
            self.assertNotIn("historical_2024_h2_coverage", result)

    def test_january_actuals_are_accepted_but_previous_year_and_forecasts_are_not(self):
        items = [{"asOfDate": day, "periodType": "3M", "currencyCode": "USD", "reportedValue": {"raw": 0}} for day in ["2023-12-31", "2024-03-31", "2027-03-31"]]
        rows = info.parse_yahoo_financials({"timeseries": {"result": [{"meta": {"symbol": ["TEST"]}, "quarterlyOperatingIncome": items}]}}, "TEST", "2026-10-26")
        self.assertEqual([row["period_end"] for row in rows], ["2023-12-31", "2024-03-31"])


if __name__ == "__main__":
    unittest.main()
