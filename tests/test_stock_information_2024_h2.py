from datetime import date
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_stock_information_2024_h2 as recovery
from backfill_stock_information_2024_h2 import merge
from backfill_sector_history_2024_h2 import reconstruct, previous_month


class HistoricalInformationTests(unittest.TestCase):
    def test_euronext_mapping_requires_one_matching_company_venue_and_currency(self):
        row = {"ticker": "EURONEXT:EXAMPLE"}
        listing = {"description": "Example Industries", "currency": "EUR"}
        def response(url):
            symbol = url.split("/chart/")[1].split("?")[0]
            return {"chart": {"result": [{"meta": {"symbol": symbol, "exchangeName": "PAR", "instrumentType": "EQUITY", "currency": "EUR", "longName": "Example Industries"}}]}}
        with tempfile.TemporaryDirectory() as folder, patch.object(recovery, "STATE", Path(folder)), patch.object(recovery, "european_listings", return_value={row["ticker"]: listing}), patch.object(recovery.info, "fetch_json", side_effect=response):
            self.assertEqual(recovery.resolve_yahoo(row), "EXAMPLE.PA")
        with tempfile.TemporaryDirectory() as folder, patch.object(recovery, "STATE", Path(folder)), patch.object(recovery, "european_listings", return_value={row["ticker"]: {**listing, "currency": "USD"}}), patch.object(recovery.info, "fetch_json", side_effect=response):
            self.assertIsNone(recovery.resolve_yahoo(row))

    def test_add_old_report_without_losing_latest_quote_or_metrics(self):
        old = {"quote": {"price": 250}, "metrics": {"per": 20}, "financials": [
            {"type": "annual", "period_end": "2025-12-31", "currency": "KRW", "revenue": 100, "source": "original"}]}
        row = {"type": "annual", "period_end": "2024-12-31", "currency": "KRW", "revenue": 0, "operating_income": -5, "source": "original"}
        result = merge(old, [row], "2026-10-21T00:00:00Z")
        self.assertEqual(result["quote"], old["quote"])
        self.assertEqual(result["metrics"], old["metrics"])
        self.assertEqual(result["financials"][0]["operating_income"], -5)
        self.assertEqual(result["financials"][0]["revenue"], 0)
        self.assertEqual(result["historical_2024_h2_coverage"]["annual_periods"], 1)
        self.assertEqual(result["historical_2024_h2_coverage"]["quarterly_periods"], 0)
        self.assertEqual(merge(result, [row], "2026-10-22T00:00:00Z")["financials"], result["financials"])
        self.assertNotIn("requested_start", old, "Original input must remain unchanged")

    def test_reconstruction_uses_past_prices_and_never_current_cap_or_return(self):
        stock = {"ticker": "000660.KS", "price": 999, "market_cap": 100000, "returns": {"day": 999}}
        history = {date(2024, 6, 28): ["20240628", 100, 100, 100, 100, 10],
                   date(2024, 7, 1): ["20240701", 100, 120, 100, 110, 20],
                   date(2024, 7, 2): ["20240702", 110, 999, 110, 999, 10]}
        value = reconstruct(stock, history, date(2024, 7, 1))
        self.assertEqual(value["price"], 110)
        self.assertAlmostEqual(value["returns"]["day"], 10)
        self.assertIsNone(value["returns"]["year"])
        self.assertIsNone(value["market_cap"])
        self.assertEqual(value["turnover"], 2200)
        self.assertEqual(previous_month(date(2024, 8, 31), 6), date(2024, 2, 29))
        self.assertIsNone(reconstruct(stock, history, date(2024, 7, 3)))


if __name__ == "__main__":
    unittest.main()
