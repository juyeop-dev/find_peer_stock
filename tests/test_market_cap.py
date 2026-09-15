from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "quote_sources"))

import market_cap  # noqa: E402


class MarketCapTests(unittest.TestCase):
    def test_symbol_candidates_cover_supported_markets(self) -> None:
        self.assertEqual(market_cap._symbol_candidates("005930.KS"), [("korea", "KRX:005930")])
        self.assertEqual(market_cap._symbol_candidates("2408.TW"), [("taiwan", "TWSE:2408")])
        self.assertEqual(market_cap._symbol_candidates("5803.T"), [("japan", "TSE:5803")])
        self.assertEqual(market_cap._symbol_candidates("0981.HK"), [("hongkong", "HKEX:981")])
        self.assertEqual(
            market_cap._symbol_candidates("MU"),
            [("america", "NASDAQ:MU"), ("america", "NYSE:MU"), ("america", "AMEX:MU")],
        )
        self.assertEqual(market_cap._source_symbol_candidate("EURONEXT:A5G"), [("global", "EURONEXT:A5G")])

    def test_explicit_source_symbol_supports_new_high_only_exchanges(self) -> None:
        def response(url, payload, _timeout):
            if "/global/" in url:
                self.assertEqual(payload["symbols"]["tickers"], ["EURONEXT:A5G"])
                return {"data": [{"s": "EURONEXT:A5G", "d": ["A5G", 8_500_000_000, "EUR"]}]}
            if "/forex/" in url:
                return {"data": [{"s": "FX_IDC:USDEUR", "d": ["USDEUR", 0.85, "EUR"]}]}
            self.fail(f"Unexpected URL: {url}")

        with patch.object(market_cap, "_request_json", side_effect=response):
            result = market_cap.fetch_market_caps(
                ["A5G.PA"], source_symbols={"A5G.PA": "EURONEXT:A5G"}
            )

        self.assertEqual(result["A5G.PA"].currency, "EUR")
        self.assertEqual(result["A5G.PA"].value_usd, 10_000_000_000)

    def test_fetch_market_caps_converts_local_values_to_usd(self) -> None:
        def response(url, payload, _timeout):
            if "/taiwan/" in url:
                return {"data": [{"s": "TWSE:2408", "d": ["2408", 1_600_000_000_000, "TWD"]}]}
            if "/america/" in url:
                return {"data": [{"s": "NASDAQ:MU", "d": ["MU", 900_000_000_000, "USD"]}]}
            if "/forex/" in url:
                self.assertIn("FX_IDC:USDTWD", payload["symbols"]["tickers"])
                return {"data": [{"s": "FX_IDC:USDTWD", "d": ["USDTWD", 32, "TWD"]}]}
            self.fail(f"Unexpected URL: {url}")

        with patch.object(market_cap, "_request_json", side_effect=response):
            result = market_cap.fetch_market_caps(["2408.TW", "MU"])

        self.assertEqual(result["2408.TW"].currency, "TWD")
        self.assertEqual(result["2408.TW"].value_usd, 50_000_000_000)
        self.assertEqual(result["MU"].value_usd, 900_000_000_000)

    def test_one_failed_region_does_not_discard_other_market_caps(self) -> None:
        def response(url, _payload, _timeout):
            if "/taiwan/" in url:
                raise market_cap.MarketCapError("Taiwan unavailable")
            if "/america/" in url:
                return {"data": [{"s": "NASDAQ:MU", "d": ["MU", 900_000_000_000, "USD"]}]}
            self.fail(f"Unexpected URL: {url}")

        with patch.object(market_cap, "_request_json", side_effect=response):
            result = market_cap.fetch_market_caps(["2408.TW", "MU"])

        self.assertNotIn("2408.TW", result)
        self.assertEqual(result["MU"].value, 900_000_000_000)


if __name__ == "__main__":
    unittest.main()
