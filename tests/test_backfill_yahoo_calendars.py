from __future__ import annotations

import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import date, datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_yahoo_calendars as backfill  # noqa: E402


class YahooCalendarBackfillTests(unittest.TestCase):
    def test_unavailable_old_range_requires_verified_later_listing_metadata(self):
        row = {"exchange": "AMEX", "name": "NEW", "symbol": "AMEX:NEW", "currency": "USD", "description": "New Company"}
        meta = {"symbol": "NEW", "instrumentType": "EQUITY", "currency": "USD", "longName": "New Company",
                "firstTradeDate": int(datetime(2023, 1, 3, tzinfo=timezone.utc).timestamp())}
        for changes, excluded in [({}, True), ({"symbol": "OTHER"}, False), ({"currency": "EUR"}, False),
                                  ({"firstTradeDate": int(datetime(2020, 1, 3, tzinfo=timezone.utc).timestamp())}, False)]:
            with self.subTest(changes=changes), patch.object(backfill, 'request_yahoo', side_effect=[
                    backfill.BackfillError('HTTP Error 400: Bad Request'), {"chart": {"result": [{"meta": {**meta, **changes}}]}}]):
                with self.assertRaises(backfill.BackfillError) as error:
                    backfill.fetch_listing_history(row, date(2021, 1, 1), date(2021, 12, 31), timeout=1, cache_dir=Path('unused'))
                self.assertEqual(isinstance(error.exception, backfill.NoRequestedSession), excluded)

    def test_yahoo_candidates_cover_configured_markets(self) -> None:
        cases = [
            ({"exchange": "TSE", "name": "7203", "symbol": "TSE:7203"}, ["7203.T"]),
            ({"exchange": "SSE", "name": "600000", "symbol": "SSE:600000"}, ["600000.SS"]),
            ({"exchange": "XETR", "name": "SAP", "symbol": "XETR:SAP"}, ["SAP.DE"]),
            ({"exchange": "TWSE", "name": "2330", "symbol": "TWSE:2330"}, ["2330.TW"]),
            ({"exchange": "TPEX", "name": "6488", "symbol": "TPEX:6488"}, ["6488.TWO"]),
            ({"exchange": "NASDAQ", "name": "AAPL", "symbol": "NASDAQ:AAPL"}, ["AAPL"]),
            ({"exchange": "EURONEXT", "name": "AIR", "symbol": "EURONEXT:AIR"},
             ["AIR.PA", "AIR.AS", "AIR.BR", "AIR.LS", "AIR.IR"]),
        ]
        for row, expected in cases:
            self.assertEqual(backfill.yahoo_candidates(row), expected)

    def test_parse_bars_does_not_double_adjust_native_split_adjusted_quotes(self) -> None:
        stamp1 = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())
        stamp2 = int(datetime(2026, 9, 2, tzinfo=timezone.utc).timestamp())
        payload = {"chart": {"result": [{
            "timestamp": [stamp1, stamp2],
            "indicators": {"quote": [{
                "open": [25, 25], "high": [30, 30], "low": [22.5, 20],
                "close": [27.5, 28], "volume": [4000, 5000],
            }]},
            "events": {"splits": {str(stamp2): {
                "date": stamp2, "numerator": 4.0, "denominator": 1.0,
            }}},
        }], "error": None}}
        bars = backfill.parse_bars(payload, "TEST", "UTC")
        self.assertEqual(bars[0].high, 30)
        self.assertEqual(bars[0].close, 27.5)
        self.assertEqual(bars[0].volume, 4000)
        self.assertEqual(bars[1].close, 28)

    def test_daily_candidate_uses_prior_close_and_52_week_high(self) -> None:
        row = {"symbol": "TSE:1"}
        history = backfill.ListingHistory(row, "1.T", [
            backfill.Bar(date(2026, 8, 31), 90, 100, 80, 95, 10),
            backfill.Bar(date(2026, 9, 1), 95, 110, 90, 105, 20),
            backfill.Bar(date(2026, 9, 2), 110, 120, 100, 105, 30),
        ])
        result = backfill.daily_candidates(history, {date(2026, 9, 1), date(2026, 9, 2)})
        self.assertTrue(result[date(2026, 9, 1)][2])
        self.assertFalse(result[date(2026, 9, 2)][2])

    def test_zero_volume_day_is_not_a_new_high(self) -> None:
        history = backfill.ListingHistory({"symbol": "TSE:1"}, "1.T", [
            backfill.Bar(date(2026, 9, 1), 100, 110, 100, 110, 0),
        ])
        self.assertEqual(backfill.daily_candidates(history, {date(2026, 9, 1)}), {})
        self.assertNotIn("europe", backfill.SUPPORTED_MARKETS)

    def test_monthly_parser_can_merge_duplicate_dates(self) -> None:
        stamp = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())
        payload = {"chart": {"result": [{
            "timestamp": [stamp, stamp],
            "indicators": {"quote": [{
                "open": [10, 11], "high": [12, 15], "low": [9, 10],
                "close": [11, 14], "volume": [100, 200],
            }]},
        }], "error": None}}
        with self.assertRaises(backfill.BackfillError):
            backfill.parse_bars(payload, "TEST", "UTC")
        bars = backfill.parse_bars(payload, "TEST", "UTC", merge_duplicates=True)
        self.assertEqual((bars[0].open, bars[0].high, bars[0].close, bars[0].volume), (10, 15, 14, 300))

    def test_request_dates_reject_reverse_range(self) -> None:
        with self.assertRaises(backfill.BackfillError):
            backfill.requested_dates(date(2026, 9, 2), date(2026, 9, 1))

    def test_company_name_guard_rejects_wrong_euronext_symbol(self) -> None:
        self.assertTrue(backfill._company_name_matches("Airbus SE", {"longName": "Airbus SE"}))
        self.assertTrue(backfill._company_name_matches("Toyota Motor Corporation", {"shortName": "TOYOTA MOTOR CORP"}))
        self.assertFalse(backfill._company_name_matches("Airbus SE", {"longName": "Air Liquide S.A."}))


if __name__ == "__main__":
    unittest.main()
