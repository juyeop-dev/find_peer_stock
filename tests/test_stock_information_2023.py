from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_stock_information_2023 as year2023
import backfill_stock_information_2024_h2 as recovery
from extend_stock_history_2023 import join_prices


class Historical2023Tests(unittest.TestCase):
    def test_2023_request_is_bounded_and_later_financials_survive(self):
        names = ["START", "END", "STATE", "AUDIT", "TABLE", "COVERAGE_KEY", "FETCHED_KEY", "RESUME"]
        with patch.multiple(recovery, **{name: getattr(recovery, name) for name in names}):
            year2023.configure()
            original = {"financials": [{"type": "annual", "period_end": "2024-12-31", "currency": "USD", "source": "original", "revenue": 7}]}
            historical = {"type": "annual", "period_end": "2023-12-31", "currency": "USD", "source": "reported", "revenue": 0, "operating_income": -1}
            value = recovery.merge(original, [historical], "2026-10-27T00:00:00Z")
            self.assertEqual(value["historical_2023_coverage"]["periods"], 1)
            self.assertEqual(value["financials"], [historical, original["financials"][0]])
            with patch.object(recovery.info, "fetch_json", return_value={"timeseries": {"result": []}}) as fetch:
                recovery.fetch({"ticker": "AAPL", "market": "us"})
                self.assertIn("period1=1672531200", fetch.call_args.args[0])
                self.assertIn("period2=1704067200", fetch.call_args.args[0])

    def test_only_matching_overlap_can_extend_a_price_series(self):
        previous = {"ticker": "TEST", "currency": "USD", "prices": [["2023-12-20", 10, 10], ["2023-12-21", 11, 11], ["2023-12-22", 12, 12], ["2026-10-26", 20, 20]]}
        older = {"ticker": "TEST", "currency": "USD", "prices": [["2023-01-02", 9, 8], ["2023-12-20", 10, 9], ["2023-12-21", 11, 10], ["2023-12-22", 12, 11]]}
        value = join_prices(previous, older)
        self.assertEqual(value["prices"][0], ["2023-01-02", 9, 9])
        self.assertEqual(value["prices"][1:], previous["prices"])
        with self.assertRaises(ValueError):
            join_prices(previous, {**older, "currency": "EUR"})
        with self.assertRaises(ValueError):
            join_prices(previous, {**older, "ticker": "OTHER"})
        wrong = {**older, "prices": [[day, close * 2, adj * 2] for day, close, adj in older["prices"]]}
        self.assertIsNone(join_prices(previous, wrong))


if __name__ == "__main__":
    unittest.main()
