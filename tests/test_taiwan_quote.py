from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


QUOTE_SOURCE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "quote_sources"
sys.path.insert(0, str(QUOTE_SOURCE_DIR))

from taiwan_quote import (  # noqa: E402
    TaiwanQuoteUnavailable,
    fetch_taiwan_quote,
    _select_quote_row,
)
from yahoo_chart import MarketDataError  # noqa: E402


class TaiwanQuoteTests(unittest.TestCase):
    def test_select_quote_row_uses_latest_trading_day(self) -> None:
        rows = [
            ["115/05/15", "110.00"],
            ["115/05/18", "111.00"],
        ]

        self.assertEqual(_select_quote_row(rows), rows[-1])

    def test_fetch_does_not_fall_back_to_previous_month_on_fetch_error(self) -> None:
        with patch(
            "taiwan_quote._fetch_twse_stock_day_quote",
            side_effect=MarketDataError("network failed"),
        ) as fetch:
            with self.assertRaises(MarketDataError):
                fetch_taiwan_quote("2303.TW")

        self.assertEqual(fetch.call_count, 1)

    def test_fetch_uses_previous_month_when_current_month_has_no_rows(self) -> None:
        expected = object()

        with patch(
            "taiwan_quote._fetch_twse_stock_day_quote",
            side_effect=[TaiwanQuoteUnavailable("empty"), expected],
        ) as fetch:
            self.assertIs(fetch_taiwan_quote("2303.TW"), expected)

        self.assertEqual(fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
