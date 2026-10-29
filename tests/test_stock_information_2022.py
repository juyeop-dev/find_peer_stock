from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_stock_information_2022 as year2022
import backfill_stock_information_2024_h2 as recovery
from extend_stock_history_2023 import join_prices


class Historical2022Tests(unittest.TestCase):
    def test_bounded_2022_recovery_preserves_later_reports_and_native_currency(self):
        names = ["START", "END", "STATE", "AUDIT", "TABLE", "COVERAGE_KEY", "FETCHED_KEY", "RESUME"]
        with patch.multiple(recovery, **{name: getattr(recovery, name) for name in names}):
            year2022.configure()
            later = {"type": "annual", "period_end": "2023-12-31", "currency": "TWD", "source": "original", "revenue": 7}
            older = {"type": "annual", "period_end": "2022-12-31", "currency": "TWD", "source": "reported", "revenue": 0, "operating_income": -1}
            value = recovery.merge({"financials": [later]}, [older], "2026-10-29T00:00:00Z")
            self.assertEqual(value["historical_2022_coverage"]["periods"], 1)
            self.assertEqual(value["financials"], [older, later])
            with patch.object(recovery.info, "fetch_json", return_value={"timeseries": {"result": []}}) as fetch:
                recovery.fetch({"ticker": "AAPL", "market": "us"})
                self.assertIn("period1=1640995200", fetch.call_args.args[0])
                self.assertIn("period2=1672531200", fetch.call_args.args[0])

    def test_2022_extension_retains_every_later_point_and_rejects_incompatible_adjustments(self):
        later = {"ticker": "TEST", "currency": "USD", "prices": [["2022-12-28", 10, 9], ["2022-12-29", 11, 10], ["2022-12-30", 12, 11], ["2026-10-28", 20, 20]]}
        older = {"ticker": "TEST", "currency": "USD", "prices": [["2021-12-30", 8, 7], *later["prices"][:3]]}
        result = join_prices(later, older, start="2021-12-20")
        self.assertEqual(result["prices"], [older["prices"][0], *later["prices"]])
        wrong = {**older, "prices": [[day, close, adjusted * .5] for day, close, adjusted in older["prices"]]}
        self.assertIsNone(join_prices(later, wrong, start="2021-12-20"))


if __name__ == "__main__":
    unittest.main()
