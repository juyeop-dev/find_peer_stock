from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_tradingview_new_highs as backfill  # noqa: E402


DAY = date(2026, 9, 10)
STAMP = int(datetime(2026, 9, 10, 6, tzinfo=timezone.utc).timestamp())


def row(symbol: str, **changes: object) -> dict:
    exchange, name = symbol.split(":", 1)
    values = {
        "symbol": symbol, "name": name, "description": f"Company {name}",
        "exchange": exchange, "type": "stock", "subtype": "common",
        "sector": "Technology", "industry": "Semiconductors",
        "currency": "JPY",
        "change": 2.5, "open": 100, "high": 150, "low": 90, "close": 110,
        "price_52_week_high": 150, "High.All": 150, "time": STAMP, "volume": 1000,
    }
    values.update(changes)
    return values


class BackfillTradingViewNewHighTests(unittest.TestCase):
    def test_requested_dates_and_offset_columns(self) -> None:
        self.assertEqual(
            backfill.requested_dates(date(2026, 9, 7), date(2026, 9, 13)),
            [date(2026, 9, day) for day in range(7, 12)],
        )
        columns = backfill.historical_columns(1)
        self.assertIn("high", columns)
        self.assertIn("high[1]", columns)
        self.assertNotIn("description[1]", columns)
        with self.assertRaises(ValueError):
            backfill.requested_dates(date(2026, 9, 10), date(2026, 9, 7))

    def test_historical_snapshot_classifies_and_filters_with_requested_bar(self) -> None:
        rows = [
            row("TSE:1000"),
            row("TSE:2000", high=120, price_52_week_high=120, **{"High.All": 150}),
            row("TSE:3000", open=120, close=110),
            row("TSE:4000", high=100, price_52_week_high=120, **{"High.All": 150}),
        ]
        reports, reviews = backfill.reports_from_rows(
            "japan", [DAY], rows, 0, minimum_coverage=1,
            collected_at="2026-09-15T00:00:00+00:00",
        )
        self.assertEqual([entry["ticker"] for entry in reports[DAY]["entries"]], ["1000.T", "2000.T"])
        self.assertEqual([entry["high_type"] for entry in reports[DAY]["entries"]], ["all_time", "52_week"])
        self.assertTrue(all(entry["currency"] == "JPY" for entry in reports[DAY]["entries"]))
        self.assertEqual(reports[DAY]["source_metadata"]["raw_new_high_candidates"], 3)
        self.assertEqual(reports[DAY]["source_metadata"]["excluded_bearish_or_down_close"], 1)
        self.assertEqual(len(reviews[DAY]["checks"]), 3)

    def test_target_date_is_matched_by_timestamp_not_assumed_offset(self) -> None:
        previous = STAMP - 86400
        rows = [row("TSE:1000", time=previous, **{
            "change[1]": 1.0, "open[1]": 90, "high[1]": 150, "low[1]": 85,
            "close[1]": 100, "price_52_week_high[1]": 150,
            "High.All[1]": 150, "time[1]": STAMP, "volume[1]": 1000,
        })]
        reports, _ = backfill.reports_from_rows(
            "japan", [DAY], rows, 1, minimum_coverage=1,
            collected_at="2026-09-15T00:00:00+00:00",
        )
        self.assertEqual(reports[DAY]["entries"][0]["high_verification"]["bar_offset"], 1)

    def test_missing_session_coverage_fails_instead_of_publishing_zero(self) -> None:
        with self.assertRaises(backfill.TradingViewSourceError):
            backfill.reports_from_rows(
                "japan", [DAY], [row("TSE:1000", time=STAMP - 86400)], 0,
                minimum_coverage=1,
            )


if __name__ == "__main__":
    unittest.main()
