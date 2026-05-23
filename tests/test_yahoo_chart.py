from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "quote_sources"))

import yahoo_chart  # noqa: E402


class YahooChartTests(unittest.TestCase):
    def test_prefers_newer_regular_market_price_over_last_intraday_bar(self) -> None:
        timezone = ZoneInfo("Asia/Tokyo")
        bar_time = datetime(2026, 5, 22, 15, 29, tzinfo=timezone)
        meta_time = datetime(2026, 5, 22, 15, 30, tzinfo=timezone)

        price, timestamp = yahoo_chart._select_latest_quote(
            {
                "regularMarketPrice": 8145,
                "regularMarketTime": int(meta_time.timestamp()),
                "exchangeTimezoneName": "Asia/Tokyo",
            },
            [int(bar_time.timestamp())],
            [8120],
        )

        self.assertEqual(price, 8145)
        self.assertEqual(timestamp, meta_time)

    def test_uses_intraday_bar_when_regular_market_price_is_stale(self) -> None:
        timezone = ZoneInfo("Asia/Tokyo")
        bar_time = datetime(2026, 5, 22, 15, 29, tzinfo=timezone)
        meta_time = datetime(2026, 5, 22, 15, 25, tzinfo=timezone)

        price, timestamp = yahoo_chart._select_latest_quote(
            {
                "regularMarketPrice": 8100,
                "regularMarketTime": int(meta_time.timestamp()),
                "exchangeTimezoneName": "Asia/Tokyo",
            },
            [int(bar_time.timestamp())],
            [8120],
        )

        self.assertEqual(price, 8120)
        self.assertEqual(timestamp, bar_time)


if __name__ == "__main__":
    unittest.main()
