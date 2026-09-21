"""Source-contract tests: incomplete data must never become a saved zero day."""

from __future__ import annotations

import copy
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from new_high_sources import tradingview as source  # noqa: E402


DAY = date(2026, 9, 11)
STAMP = int(datetime(2026, 9, 11, 13, tzinfo=timezone.utc).timestamp())


def row(symbol: str, **changes: object) -> dict:
    exchange, name = symbol.split(":", 1)
    values = {
        "name": name, "description": f"Company {name}", "exchange": exchange,
        "type": "stock", "subtype": "common", "sector": "Technology",
        "industry": "Semiconductors", "change": 2.5, "open": 95, "high": 100, "low": 90, "close": 98,
        "price_52_week_high": 120, "High.All": 150, "time": STAMP,
        "volume": 1000, "indexes": [],
        "currency": "JPY",
    }
    values.update(changes)
    return {"s": symbol, "d": [values[column] for column in source.COLUMNS]}


def response(rows: list[dict], total: int | None = None) -> dict:
    return {"totalCount": len(rows) if total is None else total, "data": rows}


class TradingViewNewHighTests(unittest.TestCase):
    def fetch(self, rows: list[dict], market: str = "japan") -> dict:
        with patch.object(source, "_request_json", return_value=response(rows)):
            return source.fetch_report(market, DAY)

    def test_full_pagination_preserves_all_time_precedence_and_ticker(self):
        rows = [
            row("TSE:1000", high=150),
            row("TSE:2000", high=120),
            row("TSE:3000"),
        ]
        with patch.object(source, "_request_json", side_effect=[response(rows[:2], 3), response(rows[2:], 3)]) as request:
            report = source.fetch_report("japan", DAY, page_size=2)
        self.assertEqual([entry["ticker"] for entry in report["entries"]], ["1000.T", "2000.T"])
        self.assertEqual([entry["high_type"] for entry in report["entries"]], ["all_time", "52_week"])
        self.assertEqual([call.args[1]["range"] for call in request.call_args_list], [[0, 2], [2, 4]])
        self.assertTrue(report["source_metadata"]["pagination_complete"])
        self.assertEqual(report["source_metadata"]["scanned_symbols"], 3)
        self.assertEqual(report["entries"][0]["reason"], "업종: Technology · Semiconductors")
        self.assertEqual(report["entries"][0]["currency"], "JPY")

    def test_intraday_high_excludes_bearish_candles_and_down_closes(self):
        rows = [
            row("TSE:1000", high=150, open=100, close=99, change=1),
            row("TSE:2000", high=150, open=100, close=101, change=-1),
            row("TSE:3000", high=150, open=100, close=100, change=0),
            row("TSE:4000", high=150, open=100, close=101, change=1),
        ]
        report = self.fetch(rows)
        self.assertEqual([entry["ticker"] for entry in report["entries"]], ["3000.T", "4000.T"])
        self.assertEqual(report["source_metadata"]["excluded_symbols"], {"bearish_or_down_close": 2})

    def test_close_filter_requires_complete_finite_prices(self):
        for changes in ({"open": None}, {"close": float("nan")}, {"change": None}, {"open": 0}):
            with self.subTest(changes=changes), self.assertRaises(source.TradingViewSourceError):
                self.fetch([row("TSE:1000", high=150, **changes)])

    def test_bearish_new_listing_without_previous_close_is_excluded(self):
        report = self.fetch([
            row("TSE:619A", high=150, open=110, close=100, change=None,
                price_52_week_high=None),
        ])
        self.assertEqual(report["entries"], [])
        self.assertEqual(report["source_metadata"]["excluded_symbols"], {"bearish_or_down_close": 1})

    def test_non_bearish_new_listing_without_previous_close_is_included(self):
        report = self.fetch([
            row("TSE:621A", high=150, open=100, close=150, change=None,
                price_52_week_high=None),
        ])
        self.assertEqual([entry["ticker"] for entry in report["entries"]], ["621A.T"])
        self.assertIsNone(report["entries"][0]["change_pct"])

    def test_zero_requires_nonempty_current_universe(self):
        report = self.fetch([row("TSE:1000")])
        self.assertEqual(report["entries"], [])
        self.assertEqual(report["source_metadata"]["current_session_reference_symbols"], {"TSE": "TSE:1000"})
        with self.assertRaises(source.TradingViewSourceError):
            self.fetch([])

    def test_stale_market_and_requested_past_session_are_not_ready(self):
        for delta in (-86400, 86400):
            with self.subTest(delta=delta), self.assertRaises(source.TradingViewSourceNotReady):
                self.fetch([row("TSE:1000", time=STAMP + delta)])

    def test_stale_symbol_is_excluded_even_if_it_made_old_high(self):
        report = self.fetch([row("TSE:1000"), row("TSE:2000", high=150, time=STAMP - 86400)])
        self.assertEqual(report["entries"], [])
        self.assertEqual(report["source_metadata"]["excluded_symbols"], {"other_session": 1})

    def test_every_configured_exchange_must_be_present_and_current(self):
        with self.assertRaisesRegex(source.TradingViewSourceError, "TPEX"):
            self.fetch([row("TWSE:2330")], "taiwan")
        with self.assertRaises(source.TradingViewSourceNotReady):
            self.fetch([row("TWSE:2330"), row("TPEX:6488", time=STAMP - 86400)], "taiwan")

    def test_taiwan_and_us_tickers_match_peer_ids(self):
        taiwan = self.fetch([row("TWSE:2330", high=150), row("TPEX:6488", high=120)], "taiwan")
        self.assertEqual({entry["ticker"] for entry in taiwan["entries"]}, {"2330.TW", "6488.TWO"})
        us = self.fetch([row("NASDAQ:AAPL", high=150), row("NYSE:IBM"), row("AMEX:ABC")], "us")
        self.assertEqual(us["entries"][0]["ticker"], "AAPL")

    def test_europe_uses_global_exchange_universe_and_qualified_tickers(self):
        rows = [row(f"{exchange}:ABC", high=150) for exchange in ("EURONEXT", "XETR", "LSE", "SIX")]
        with patch.object(source, "_request_json", return_value=response(rows)) as request:
            report = source.fetch_report("europe", DAY)
        self.assertEqual(request.call_args.args[0], "https://scanner.tradingview.com/global/scan")
        self.assertEqual({entry["exchange"] for entry in report["entries"]}, {"EURONEXT", "XETRA", "LSE", "SIX"})
        self.assertEqual(len({entry["ticker"] for entry in report["entries"]}), 4)

    def test_korean_composite_membership_and_board_metadata_fallback(self):
        rows = [
            row("KRX:005930", indexes=[{"proname": "KRX:KOSPI"}], high=150),
            row("KRX:098120", indexes=[{"proname": "KRX:KOSDAQ"}]),
            row("KRX:0197V0", high=120),
        ]
        with patch.object(source, "_request_json", side_effect=[
            response(rows),
            {"itemCode": "005930", "stockName": "삼성전자", "stockExchangeType": {"name": "KOSPI"}},
            {"itemCode": "0197V0", "stockName": "엔에이치스팩34호", "stockExchangeType": {"name": "KOSDAQ"}},
        ]) as request, patch.object(source, "verify_korean_daily_high", return_value={
            "confirmed": True, "passes_close_filter": True, "open": 100, "close": 120,
        }):
            report = source.fetch_report("korea", DAY)
        self.assertEqual({entry["ticker"] for entry in report["entries"]}, {"005930.KS", "0197V0.KQ"})
        self.assertEqual({entry["name"] for entry in report["entries"]}, {"삼성전자", "엔에이치스팩34호"})
        self.assertTrue(all(entry["description"].startswith(entry["name"] + " · ") for entry in report["entries"]))
        self.assertIn("/0197V0/basic", request.call_args.args[0])

    def test_korean_names_require_matching_code_and_nonempty_verified_name(self):
        for metadata in (
            {"itemCode": "wrong", "stockName": "다른 종목", "stockExchangeType": {"name": "KOSPI"}},
            {"itemCode": "005930", "stockName": " ", "stockExchangeType": {"name": "KOSPI"}},
        ):
            with patch.object(source, "_request_json", return_value=metadata), self.assertRaises(source.TradingViewSourceError):
                source.fetch_korean_listing("005930")

    def test_korean_daily_history_vetoes_false_new_listing_high_and_keeps_ties(self):
        # Regression: 0197V0 on Sep 11 was below its Sep 10 listing-day high.
        for high, confirmed, tied in [(2035, False, False), (5700, True, True), (5800, True, False)]:
            with patch.object(source, "_request_daily_history", return_value=[
                ["20260910", 2000, 5700, 2000, 2075, 1000],
                ["20260911", 2000, high, 1931, 1931, 7560653],
            ]):
                evidence = source.verify_korean_daily_high("0197V0", DAY)
            self.assertEqual(evidence["confirmed"], confirmed)
            self.assertEqual(evidence["matches_prior_high"], tied)

    def test_korean_daily_history_requires_non_bearish_non_down_close(self):
        cases = [
            (110, 105, 100, False),
            (100, 105, 110, False),
            (100, 100, 100, True),
            (100, 105, 100, True),
        ]
        for open_price, close, previous_close, expected in cases:
            with self.subTest(open=open_price, close=close, previous_close=previous_close), \
                    patch.object(source, "_request_daily_history", return_value=[
                        ["20260910", 100, 120, 90, previous_close, 1000],
                        ["20260911", open_price, 150, 90, close, 1000],
                    ]):
                evidence = source.verify_korean_daily_high("005930", DAY)
            self.assertEqual(evidence["passes_close_filter"], expected)

    def test_daily_history_missing_target_bad_values_and_duplicates_fail(self):
        good = ["20260911", 100, 150, 90, 120, 1000]
        for rows in ([], [["20260910", 100, 150, 90, 120, 1000]], [good, good],
                     [["20260911", 100, float("nan"), 90, 120, 1000]],
                     [["20260912", 100, 150, 90, 120, 1000]], [["bad"]]):
            with patch.object(source, "_request_daily_history", return_value=rows), self.assertRaises(source.TradingViewSourceError):
                source.verify_korean_daily_high("005930", DAY)
        with patch.object(source, "_request_daily_history", return_value=[["20260911", 100, 150, 90, 120, 0]]):
            self.assertFalse(source.verify_korean_daily_high("005930", DAY)["confirmed"])

    def test_korean_scanner_candidate_contradicted_by_daily_history_is_excluded(self):
        rows = [row("KRX:005930", indexes=[{"proname": "KRX:KOSPI"}]),
                row("KRX:098120", indexes=[{"proname": "KRX:KOSDAQ"}], high=150)]
        with patch.object(source, "_request_json", return_value=response(rows)), \
             patch.object(source, "fetch_korean_listing", return_value={"name": "마이크로컨텍솔", "exchange": "KOSDAQ", "source_url": "https://stock.naver.com/"}), \
             patch.object(source, "verify_korean_daily_high", return_value={"confirmed": False}):
            report = source.fetch_report("korea", DAY)
        self.assertEqual(report["entries"], [])
        self.assertEqual(report["source_metadata"]["excluded_symbols"], {"korean_daily_history_disagrees": 1})

    def test_korean_daily_close_filter_vetoes_scanner_candidate(self):
        rows = [row("KRX:005930", indexes=[{"proname": "KRX:KOSPI"}]),
                row("KRX:098120", indexes=[{"proname": "KRX:KOSDAQ"}], high=150)]
        with patch.object(source, "_request_json", return_value=response(rows)), \
             patch.object(source, "fetch_korean_listing", return_value={
                 "name": "마이크로컨텍솔", "exchange": "KOSDAQ", "source_url": "https://stock.naver.com/",
             }), patch.object(source, "verify_korean_daily_high", return_value={
                 "confirmed": True, "passes_close_filter": False, "open": 100, "close": 90,
             }):
            report = source.fetch_report("korea", DAY)
        self.assertEqual(report["entries"], [])
        self.assertEqual(report["source_metadata"]["excluded_symbols"], {"bearish_or_down_close": 1})

    def test_korean_board_cannot_be_guessed(self):
        rows = [
            row("KRX:005930", indexes=[{"proname": "KRX:KOSPI"}]),
            row("KRX:098120", indexes=[{"proname": "KRX:KOSDAQ"}]),
            row("KRX:0197V0", high=120),
        ]
        for metadata in ({"itemCode": "wrong"}, {"itemCode": "0197V0", "stockExchangeType": {"name": "KONEX"}}):
            with self.subTest(metadata=metadata), patch.object(source, "_request_json", side_effect=[response(rows), metadata]):
                with self.assertRaises(source.TradingViewSourceError):
                    source.fetch_report("korea", DAY)

    def test_new_listing_with_missing_week_high_can_prove_all_time_high(self):
        report = self.fetch([row("TSE:618A", high=150, price_52_week_high=None)])
        self.assertEqual(report["entries"][0]["high_type"], "all_time")

    def test_missing_lookback_never_becomes_zero_or_guessed_classification(self):
        for changes in (
            {"price_52_week_high": None}, {"high": 120, "High.All": None},
            {"high": None}, {"high": float("nan")}, {"High.All": float("inf")},
        ):
            with self.subTest(changes=changes), self.assertRaises(source.TradingViewSourceError):
                self.fetch([row("TSE:1000", **changes)])

    def test_missing_all_time_is_irrelevant_when_week_high_already_rules_out_new_high(self):
        self.assertEqual(self.fetch([row("TSE:1000", **{"High.All": None})])["entries"], [])

    def test_dated_prices_require_valid_timestamp(self):
        for stamp in (None, False, 0, "2026-09-11", float("inf")):
            with self.subTest(stamp=stamp), self.assertRaises(source.TradingViewSourceError):
                self.fetch([row("TSE:1000", time=stamp)])

    def test_no_price_history_is_explicitly_excluded(self):
        report = self.fetch([
            row("TSE:1000"),
            row("TSE:2000", time=None, high=None, price_52_week_high=None, volume=None, **{"High.All": None}),
        ])
        self.assertEqual(report["source_metadata"]["excluded_symbols"], {"no_price_history": 1})

    def test_incomplete_changed_and_duplicate_pages_are_rejected(self):
        first = [row("TSE:1000"), row("TSE:2000")]
        for second in (response([], 3), response([row("TSE:3000")], 4), response([first[0]], 3)):
            with self.subTest(second=second), patch.object(source, "_request_json", side_effect=[response(first, 3), second]):
                with self.assertRaises(source.TradingViewSourceError):
                    source.fetch_report("japan", DAY, page_size=2)

    def test_malformed_source_response_is_rejected(self):
        item = row("TSE:1000")
        short = copy.deepcopy(item)
        short["d"].pop()
        for payload in (None, {"totalCount": True, "data": []}, response([short]), response([row("NASDAQ:AAPL")])):
            with self.subTest(payload=payload), patch.object(source, "_request_json", return_value=payload):
                with self.assertRaises(source.TradingViewSourceError):
                    source.fetch_report("japan", DAY)

    def test_china_uses_complete_configured_sse_szse_scope_and_peer_tickers(self):
        rows = [
            row("SSE:600000", high=150, currency="CNY"),
            row("SZSE:000001", high=120, currency="CNY"),
        ]
        with patch.object(source, "_request_json", return_value=response(rows)) as request:
            report = source.fetch_report("china", DAY)
        self.assertEqual(request.call_args.args[0], "https://scanner.tradingview.com/china/scan")
        self.assertEqual({entry["ticker"] for entry in report["entries"]}, {"600000.SS", "000001.SZ"})
        self.assertEqual(set(report["source_metadata"]["scanner_exchanges"]), {"SSE", "SZSE"})


if __name__ == "__main__":
    unittest.main()
