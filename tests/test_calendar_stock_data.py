import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generate_calendar_stock_data import calendar_stocks, publish


class CalendarStockDataTests(unittest.TestCase):
    def test_prices_are_deduplicated_and_turnover_has_precedence_without_combining_currencies(self):
        def report(day, entry):
            return {"market": "europe", "date": day, "entries": [entry]}

        base = {"ticker": "LSE:A", "exchange": "LSE"}
        rows = calendar_stocks([
            ("turnover", report("2026-01-02", {**base, "price": 110, "currency": "GBX"})),
            ("new-highs", report("2026-01-02", {**base, "session_close": 100, "currency": "GBX"})),
            ("new-highs", report("2026-01-05", {**base, "session_close": 1.2, "currency": "GBP"})),
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["history"], [
            {"date": "2026-01-02", "close": 110, "currency": "GBX"},
            {"date": "2026-01-05", "close": 1.2, "currency": "GBP"},
        ])

    def test_missing_price_creates_an_empty_profile_without_inventing_prices(self):
        stock = calendar_stocks([("new-highs", {"market": "korea", "date": "2026-01-02",
            "entries": [{"ticker": "A.KS", "exchange": "KOSPI", "session_close": None}]})])[0]
        self.assertEqual(stock["history"], [])

    def test_publication_supports_colon_tickers_on_windows_and_preserves_real_dates(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "source", Path(root) / "out"
            path = source / "new-highs/reports/europe/2026-01-02.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"market": "europe", "date": "2026-01-02", "entries": [
                {"ticker": "EURONEXT:MC", "exchange": "EURONEXT", "session_close": 600}]}), encoding="utf-8")
            self.assertEqual(publish(source, output), 1)
            data = json.loads((output / "europe/EURONEXT~3AMC.json").read_text(encoding="utf-8"))
            self.assertEqual(data["history"], [{"date": "2026-01-02", "close": 600, "currency": "EUR"}])


if __name__ == "__main__":
    unittest.main()
