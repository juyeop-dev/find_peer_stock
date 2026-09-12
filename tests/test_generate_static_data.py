from __future__ import annotations

import sys
import json
import tempfile
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
    def previous_quote(self) -> dict:
        return {
            "ticker": "3026.TW", "price": 758.0, "previous_close": 747.0,
            "change": 11.0, "change_pct": 1.47, "currency": "TWD",
            "source": "Yahoo Finance", "fetched_at": "2026-09-09T23:02:08+09:00",
            "market_time": "2026-09-09T13:30:10+08:00", "basis_label": None,
            "status": "ok", "error": None, "refresh_status": "fetched",
        }

    def test_failed_refresh_keeps_price_and_original_timestamps(self) -> None:
        previous = self.previous_quote()
        now = datetime(2026, 9, 12, 12, 0, tzinfo=data_gen.KST)
        with patch.object(data_gen, "fetch_quote_result", side_effect=TimeoutError("provider timeout")):
            result = data_gen.build_quote_snapshot("3026.TW", generated_at=now, no_fetch=False,
                                                   previous_quote=previous)
        for field in ("price", "previous_close", "change", "source", "fetched_at", "market_time"):
            self.assertEqual(result[field], previous[field])
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["refresh_status"], "error")
        self.assertEqual(result["last_checked_at"], now.isoformat())
        self.assertEqual(result["error"], "provider timeout")
        self.assertEqual(previous["status"], "ok")

    def test_no_fetch_does_not_erase_previous_price(self) -> None:
        previous = self.previous_quote()
        with patch.object(data_gen, "fetch_quote_result") as fetch:
            result = data_gen.build_quote_snapshot("3026.TW", generated_at=datetime.now(data_gen.KST),
                                                   no_fetch=True, previous_quote=previous)
        fetch.assert_not_called()
        self.assertEqual(result["price"], previous["price"])
        self.assertEqual(result["fetched_at"], previous["fetched_at"])
        self.assertNotIn("last_checked_at", result)
        self.assertEqual(result["refresh_status"], "not_fetched")

    def test_repeated_failure_keeps_last_success_and_recovers(self) -> None:
        previous = {**self.previous_quote(), "status": "stale", "error": "old error"}
        now = datetime.now(data_gen.KST)
        with patch.object(data_gen, "fetch_quote_result", side_effect=TimeoutError("new error")):
            stale = data_gen.build_quote_snapshot("3026.TW", generated_at=now, no_fetch=False,
                                                  previous_quote=previous)
        self.assertEqual(stale["fetched_at"], previous["fetched_at"])
        self.assertEqual(stale["price"], 758.0)
        quote = data_gen.Quote("3026.TW", 760, 758, 2, 0.26, "TWD", now)
        with patch.object(data_gen, "fetch_quote_result", return_value=data_gen.QuoteFetchResult(quote, "TWSE")):
            recovered = data_gen.build_quote_snapshot("3026.TW", generated_at=now, no_fetch=False,
                                                      previous_quote=stale)
        self.assertEqual(recovered["status"], "ok")
        self.assertEqual(recovered["price"], 760)
        self.assertIsNone(recovered["error"])
        self.assertNotIn("last_checked_at", recovered)

    def test_invalid_previous_quote_is_not_used_as_fallback(self) -> None:
        for overrides in ({"ticker": "MU"}, {"price": None}, {"price": float("nan")},
                          {"price": True}, {"price": -1}, {"status": "error"}):
            with self.subTest(overrides=overrides), patch.object(data_gen, "fetch_quote_result", side_effect=RuntimeError("failed")):
                result = data_gen.build_quote_snapshot("3026.TW", generated_at=datetime.now(data_gen.KST),
                                                       no_fetch=False, previous_quote={**self.previous_quote(), **overrides})
                self.assertIsNone(result["price"])
                self.assertEqual(result["status"], "error")

    def test_load_previous_quotes_ignores_corrupt_or_mismatched_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "stocks").mkdir()
            (output / "stocks/3026.TW.json").write_text(json.dumps({"quote": self.previous_quote()}), encoding="utf-8")
            (output / "stocks/broken.json").write_text("{", encoding="utf-8")
            (output / "stocks/array.json").write_text("[]", encoding="utf-8")
            (output / "stocks/MU.json").write_text(json.dumps({"quote": self.previous_quote()}), encoding="utf-8")
            self.assertEqual(list(data_gen.load_previous_quotes(output)), ["3026.TW"])

    def test_total_source_failure_exits_without_publishing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "seed").mkdir()
            (root / "seed/example.json").write_text(json.dumps({"target": {"ticker": "3026.TW"}}), encoding="utf-8")
            output = root / "generated"
            (output / "stocks").mkdir(parents=True)
            snapshot = output / "stocks/3026.TW.json"
            original = json.dumps({"quote": self.previous_quote()})
            snapshot.write_text(original, encoding="utf-8")
            argv = ["generate_static_data.py", "--seed-dir", str(root / "seed"), "--output-dir", str(output)]
            with patch.object(sys, "argv", argv), patch.object(data_gen, "fetch_quote_result", side_effect=RuntimeError("offline")), \
                 patch.object(data_gen, "write_static_data") as write, patch.object(data_gen, "sync_frontend_data") as sync:
                with self.assertRaisesRegex(SystemExit, "No quotes fetched"):
                    data_gen.main()
                write.assert_not_called()
                sync.assert_not_called()
            self.assertEqual(snapshot.read_text(encoding="utf-8"), original)

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

        with patch.object(
            data_gen,
            "fetch_quote_result",
            return_value=data_gen.QuoteFetchResult(quote, "TWSE"),
        ) as fetch_quote:
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

    def test_taiwan_tw_falls_back_to_twse_when_yahoo_is_unavailable(self) -> None:
        twse_quote = data_gen.Quote(
            ticker="3026.TW",
            price=764.0,
            previous_close=695.0,
            change=69.0,
            change_pct=9.928057553956826,
            currency="TWD",
            timestamp=datetime(2026, 6, 12, 13, 30, 30, tzinfo=ZoneInfo("Asia/Taipei")),
            basis_label=None,
        )
        generated_at = datetime(2026, 6, 12, 20, 51, tzinfo=data_gen.KST)

        with (
            patch.object(data_gen, "fetch_latest_quote", side_effect=data_gen.MarketDataError("Yahoo unavailable")),
            patch.object(data_gen, "fetch_taiwan_quote", return_value=twse_quote) as fetch_twse,
        ):
            snapshot = data_gen.build_quote_snapshot(
                "3026.TW",
                generated_at=generated_at,
                no_fetch=False,
                previous_quote=None,
            )

        fetch_twse.assert_called_once_with("3026.TW")
        self.assertEqual(snapshot["price"], 764.0)
        self.assertEqual(snapshot["source"], "TWSE")
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(snapshot["refresh_status"], "fetched")
        self.assertIn("outside refresh window", snapshot["market_status_reason"])

    def test_taiwan_tw_uses_yahoo_after_close_even_when_twse_is_available(self) -> None:
        yahoo_quote = data_gen.Quote(
            ticker="2327.TW",
            price=855.0,
            previous_close=842.0,
            change=13.0,
            change_pct=1.5439429928741033,
            currency="TWD",
            timestamp=datetime(2026, 6, 12, 13, 30, 1, tzinfo=ZoneInfo("Asia/Taipei")),
            basis_label=None,
        )
        generated_at = datetime(2026, 6, 12, 20, 51, tzinfo=data_gen.KST)

        with (
            patch.object(data_gen, "fetch_latest_quote", return_value=yahoo_quote) as fetch_latest,
            patch.object(data_gen, "fetch_taiwan_quote", side_effect=AssertionError("TWSE should be fallback only")),
        ):
            snapshot = data_gen.build_quote_snapshot(
                "2327.TW",
                generated_at=generated_at,
                no_fetch=False,
                previous_quote=None,
            )

        fetch_latest.assert_called_once_with("2327.TW")
        self.assertEqual(snapshot["price"], 855.0)
        self.assertEqual(snapshot["previous_close"], 842.0)
        self.assertEqual(snapshot["change"], 13.0)
        self.assertEqual(snapshot["change_pct"], 1.5439429928741033)
        self.assertEqual(snapshot["source"], "Yahoo Finance")
        self.assertEqual(snapshot["status"], "ok")

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

        with patch.object(
            data_gen,
            "fetch_quote_result",
            return_value=data_gen.QuoteFetchResult(quote, "Yahoo Finance"),
        ) as fetch_quote:
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

        with patch.object(
            data_gen,
            "fetch_quote_result",
            return_value=data_gen.QuoteFetchResult(quote, "Yahoo Finance"),
        ) as fetch_quote:
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

        with patch.object(
            data_gen,
            "fetch_quote_result",
            return_value=data_gen.QuoteFetchResult(quote, "TWSE"),
        ) as fetch_quote:
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

        with patch.object(
            data_gen,
            "fetch_quote_result",
            return_value=data_gen.QuoteFetchResult(quote, "Yahoo Finance"),
        ) as fetch_quote:
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
