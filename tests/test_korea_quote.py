from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


QUOTE_SOURCE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "quote_sources"
sys.path.insert(0, str(QUOTE_SOURCE_DIR))

from korea_quote import fetch_korean_quote  # noqa: E402
from yahoo_chart import MarketDataError  # noqa: E402


class KoreaQuoteTests(unittest.TestCase):
    def test_scanner_fallback_does_not_invent_market_time(self) -> None:
        payload = {
            "data": [
                {
                    "s": "KRX:009150",
                    "d": ["009150", 1404000, 2.48, 34000, "KRW", "KRX"],
                }
            ]
        }
        response = io.BytesIO(json.dumps(payload).encode("utf-8"))

        with (
            patch(
                "korea_quote._fetch_naver_finance_quote",
                side_effect=MarketDataError("Naver unavailable"),
            ),
            patch("korea_quote.urllib.request.urlopen", return_value=response),
        ):
            quote = fetch_korean_quote("009150.KS")

        self.assertEqual(quote.price, 1404000)
        self.assertEqual(quote.previous_close, 1370000)
        self.assertEqual(quote.change_pct, 2.48)
        self.assertEqual(quote.currency, "KRW")
        self.assertIsNone(quote.timestamp)


if __name__ == "__main__":
    unittest.main()
