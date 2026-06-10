from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import generate_static_data as data_gen  # noqa: E402


class GenerateStaticDataTests(unittest.TestCase):
    def test_normalize_company_prefers_company_info_metadata(self) -> None:
        profile = data_gen.normalize_company(
            {
                "name_kr": "Seed Name",
                "name_en": "Seed English",
                "ticker": "6239.TW",
                "sector": "Memory packaging / test",
                "note": "Event note",
            },
            company_info={
                "6239.TW": {
                    "name_kr": "Canonical Name",
                    "name_en": "Powertech Technology",
                    "description": "Memory packaging and test",
                    "country": "Taiwan",
                    "primary_category": "semiconductor",
                }
            },
        )

        self.assertEqual(profile["name_kr"], "Canonical Name")
        self.assertEqual(profile["name_en"], "Powertech Technology")
        self.assertEqual(profile["country"], "Taiwan")
        self.assertEqual(profile["market_note"], "Memory packaging and test")
        self.assertEqual(profile["note"], "Event note")

    def test_tpex_ticker_uses_taiwan_schedule_and_yahoo_source(self) -> None:
        self.assertEqual(data_gen.infer_country("6175.TWO"), "대만")
        self.assertEqual(data_gen.infer_currency("6175.TWO"), "TWD")
        self.assertEqual(data_gen.infer_source("6175.TWO"), "Yahoo Finance")

    def test_pre_open_fetches_quote_instead_of_reusing_previous_quote(self) -> None:
        quote = data_gen.Quote(
            ticker="2303.TW",
            price=112.0,
            previous_close=110.0,
            change=2.0,
            change_pct=1.8181818181818181,
            currency="TWD",
            timestamp=datetime(2026, 5, 18, 8, 30, tzinfo=ZoneInfo("Asia/Taipei")),
            basis_label=None,
        )
        previous_quote = {
            "ticker": "2303.TW",
            "price": 111.0,
            "previous_close": 110.0,
            "change": 1.0,
            "change_pct": 0.9090909090909091,
            "currency": "TWD",
            "source": "TWSE",
            "fetched_at": "2026-05-15T17:00:00+09:00",
            "market_time": "2026-05-15T13:30:00+08:00",
            "basis_label": None,
            "status": "ok",
            "error": None,
        }
        generated_at = datetime(2026, 5, 18, 9, 30, tzinfo=data_gen.KST)

        with patch.object(data_gen, "fetch_quote", return_value=quote) as fetch_quote:
            snapshot = data_gen.build_quote_snapshot(
                "2303.TW",
                generated_at=generated_at,
                no_fetch=False,
                previous_quote=previous_quote,
            )

        fetch_quote.assert_called_once()
        self.assertEqual(snapshot["price"], 112.0)
        self.assertEqual(snapshot["change"], 2.0)
        self.assertEqual(snapshot["change_pct"], 1.8181818181818181)
        self.assertEqual(snapshot["refresh_status"], "fetched")
        self.assertEqual(snapshot["fetched_at"], generated_at.isoformat())
        self.assertNotIn("last_checked_at", snapshot)
        self.assertEqual(snapshot["market_status"], "closed")
        self.assertIn("before regular session open", snapshot["market_status_reason"])

    def test_taiwan_tw_uses_yahoo_intraday_during_regular_session(self) -> None:
        quote = data_gen.Quote(
            ticker="2492.TW",
            price=275.0,
            previous_close=266.0,
            change=9.0,
            change_pct=3.383458646616541,
            currency="TWD",
            timestamp=datetime(2026, 5, 22, 10, 0, tzinfo=ZoneInfo("Asia/Taipei")),
            basis_label=None,
        )
        generated_at = datetime(2026, 5, 22, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))

        with (
            patch.object(data_gen, "fetch_latest_quote", return_value=quote) as fetch_latest,
            patch.object(data_gen, "fetch_taiwan_quote", side_effect=AssertionError("TWSE daily should not be used")),
        ):
            snapshot = data_gen.build_quote_snapshot(
                "2492.TW",
                generated_at=generated_at,
                no_fetch=False,
                previous_quote=None,
            )

        fetch_latest.assert_called_once_with("2492.TW")
        self.assertEqual(snapshot["price"], 275.0)
        self.assertEqual(snapshot["source"], "Yahoo Finance")
        self.assertEqual(snapshot["refresh_status"], "fetched")

    def test_post_close_refresh_window_fetches_instead_of_reusing_previous_quote(self) -> None:
        quote = data_gen.Quote(
            ticker="6976.T",
            price=8145.0,
            previous_close=7861.0,
            change=284.0,
            change_pct=3.6127719119704915,
            currency="JPY",
            timestamp=datetime(2026, 5, 22, 15, 30, tzinfo=ZoneInfo("Asia/Tokyo")),
            basis_label=None,
        )
        previous_quote = {
            "ticker": "6976.T",
            "price": 8000.0,
            "previous_close": 7861.0,
            "change": 139.0,
            "change_pct": 1.768222872408092,
            "currency": "JPY",
            "source": "Yahoo Finance",
            "fetched_at": "2026-05-22T15:25:00+09:00",
            "market_time": "2026-05-22T15:25:00+09:00",
            "basis_label": None,
            "status": "ok",
            "error": None,
        }
        generated_at = datetime(2026, 5, 22, 15, 30, 15, tzinfo=ZoneInfo("Asia/Tokyo"))

        with patch.object(data_gen, "fetch_quote", return_value=quote) as fetch_quote:
            snapshot = data_gen.build_quote_snapshot(
                "6976.T",
                generated_at=generated_at,
                no_fetch=False,
                previous_quote=previous_quote,
            )

        fetch_quote.assert_called_once()
        self.assertEqual(snapshot["price"], 8145.0)
        self.assertEqual(snapshot["refresh_status"], "fetched")
        self.assertEqual(snapshot["market_status"], "closed")
        self.assertIn("post-close refresh window", snapshot["market_status_reason"])

    def test_after_refresh_window_fetches_instead_of_reusing_previous_quote(self) -> None:
        quote = data_gen.Quote(
            ticker="6976.T",
            price=8200.0,
            previous_close=7861.0,
            change=339.0,
            change_pct=4.312428444218293,
            currency="JPY",
            timestamp=datetime(2026, 5, 22, 15, 30, tzinfo=ZoneInfo("Asia/Tokyo")),
            basis_label=None,
        )
        previous_quote = {
            "ticker": "6976.T",
            "price": 8145.0,
            "previous_close": 7861.0,
            "change": 284.0,
            "change_pct": 3.6127719119704915,
            "currency": "JPY",
            "source": "Yahoo Finance",
            "fetched_at": "2026-05-22T15:35:00+09:00",
            "market_time": "2026-05-22T15:30:00+09:00",
            "basis_label": None,
            "status": "ok",
            "error": None,
        }
        generated_at = datetime(2026, 5, 22, 16, 31, tzinfo=ZoneInfo("Asia/Tokyo"))

        with patch.object(data_gen, "fetch_quote", return_value=quote) as fetch_quote:
            snapshot = data_gen.build_quote_snapshot(
                "6976.T",
                generated_at=generated_at,
                no_fetch=False,
                previous_quote=previous_quote,
            )

        fetch_quote.assert_called_once()
        self.assertEqual(snapshot["price"], 8200.0)
        self.assertEqual(snapshot["refresh_status"], "fetched")
        self.assertEqual(snapshot["fetched_at"], generated_at.isoformat())
        self.assertNotIn("last_checked_at", snapshot)
        self.assertIn("outside refresh window", snapshot["market_status_reason"])

    def test_market_closed_without_previous_quote_initializes_quote(self) -> None:
        quote = data_gen.Quote(
            ticker="6239.TW",
            price=181.0,
            previous_close=164.5,
            change=16.5,
            change_pct=10.030395136778116,
            currency="TWD",
            timestamp=datetime(2026, 5, 22, 13, 30, tzinfo=ZoneInfo("Asia/Taipei")),
            basis_label=None,
        )
        generated_at = datetime(2026, 5, 23, 12, 0, tzinfo=data_gen.KST)

        with patch.object(data_gen, "fetch_quote", return_value=quote) as fetch_quote:
            snapshot = data_gen.build_quote_snapshot(
                "6239.TW",
                generated_at=generated_at,
                no_fetch=False,
                previous_quote=None,
            )

        fetch_quote.assert_called_once()
        self.assertEqual(snapshot["price"], 181.0)
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(snapshot["refresh_status"], "fetched")
        self.assertEqual(snapshot["market_status"], "closed")

    def test_market_closed_error_previous_quote_is_not_reused(self) -> None:
        quote = data_gen.Quote(
            ticker="9984.T",
            price=9020.0,
            previous_close=8060.0,
            change=960.0,
            change_pct=11.910669975186104,
            currency="JPY",
            timestamp=datetime(2026, 5, 22, 15, 30, tzinfo=ZoneInfo("Asia/Tokyo")),
            basis_label=None,
        )
        previous_quote = {
            "ticker": "9984.T",
            "price": None,
            "previous_close": None,
            "change": None,
            "change_pct": None,
            "currency": "JPY",
            "source": "Yahoo Finance",
            "fetched_at": "2026-05-23T12:00:00+09:00",
            "market_time": None,
            "basis_label": None,
            "status": "error",
            "error": "market closed; no previous quote available",
        }
        generated_at = datetime(2026, 5, 23, 12, 5, tzinfo=data_gen.KST)

        with patch.object(data_gen, "fetch_quote", return_value=quote) as fetch_quote:
            snapshot = data_gen.build_quote_snapshot(
                "9984.T",
                generated_at=generated_at,
                no_fetch=False,
                previous_quote=previous_quote,
            )

        fetch_quote.assert_called_once()
        self.assertEqual(snapshot["price"], 9020.0)
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(snapshot["refresh_status"], "fetched")

    def test_all_markets_fetch_during_first_hour_after_final_close(self) -> None:
        cases = [
            ("005930.KS", datetime(2026, 5, 22, 16, 0, tzinfo=ZoneInfo("Asia/Seoul"))),
            ("6976.T", datetime(2026, 5, 22, 16, 0, tzinfo=ZoneInfo("Asia/Tokyo"))),
            ("2492.TW", datetime(2026, 5, 22, 14, 0, tzinfo=ZoneInfo("Asia/Taipei"))),
            ("0700.HK", datetime(2026, 5, 22, 16, 30, tzinfo=ZoneInfo("Asia/Hong_Kong"))),
            ("600584.SS", datetime(2026, 5, 22, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))),
            ("MU", datetime(2026, 5, 22, 16, 30, tzinfo=ZoneInfo("America/New_York"))),
        ]

        for ticker, current_time in cases:
            with self.subTest(ticker=ticker):
                state = data_gen.get_market_state(ticker, current_time)
                self.assertFalse(state.is_open)
                self.assertTrue(state.should_fetch)
                self.assertIn("post-close refresh window", state.reason)


if __name__ == "__main__":
    unittest.main()
