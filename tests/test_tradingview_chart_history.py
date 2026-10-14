from __future__ import annotations

import json
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quote_sources import tradingview_chart as chart
from backfill_european_new_highs import Bar, candidates, chart_bars, classify_high, completed_through, stamp_date, validate_session_coverage, verify_series_end


class TradingViewChartHistoryTests(unittest.TestCase):
    def test_framing_reads_concatenated_heartbeat_and_unicode(self):
        body = json.dumps({"description": "München ® 🚀"}, ensure_ascii=False)
        heartbeat = "~h~123"
        frame = f"~m~{len(body.encode('utf-16-le')) // 2}~m~{body}~m~{len(heartbeat)}~m~{heartbeat}"
        self.assertEqual(chart.decode_messages(frame), [body, heartbeat])
        for invalid in ["invalid", "~m~x~m~{}", "~m~4~m~{}"]:
            with self.assertRaises(chart.ChartHistoryError):
                chart.decode_messages(invalid)

    def test_volume_is_required_for_daily_but_not_old_monthly_bars(self):
        points = [{"v": [-315619200, 90, 110, 80, 100, None]}]
        with self.assertRaises(chart.ChartHistoryError):
            chart.parse_chart_bars(points)
        result = chart.parse_chart_bars(points, require_volume=False)
        self.assertEqual(result[0]["volume"], 0)
        self.assertEqual(stamp_date(result[0]["timestamp"], "UTC"), date(1960, 1, 1))

    def test_missing_london_low_is_preserved_without_fabricating_a_price(self):
        result = chart.parse_chart_bars([{"v": [1779951600, 11.22, 11.48, 0, 11.4597, 7088]}])
        self.assertEqual(result[0]["low"], 0)
        self.assertEqual(result[0]["high"], 11.48)
        with self.assertRaises(chart.ChartHistoryError):
            chart.parse_chart_bars([{"v": [1779951600, 0, 11.48, 0, 11.4597, 7088]}])

    def test_zero_volume_bearish_and_down_close_are_excluded(self):
        bars = [Bar(date(2026, 8, 3), 90, 100, 80, 95, 10),
                Bar(date(2026, 8, 4), 95, 110, 90, 105, 0),
                Bar(date(2026, 8, 5), 110, 120, 100, 105, 10),
                Bar(date(2026, 8, 6), 90, 125, 80, 100, 10),
                Bar(date(2026, 8, 7), 100, 130, 90, 130, 10)]
        result = candidates(bars, {bar.day for bar in bars[1:]})
        self.assertEqual(list(result), [date(2026, 8, 7)])
        self.assertEqual(result[date(2026, 8, 7)]["previous"].close, 100)

    def test_52_week_window_excludes_older_and_future_peaks(self):
        bars = [Bar(date(2025, 7, 1), 50, 1000, 40, 50, 10),
                Bar(date(2025, 8, 4), 50, 90, 40, 50, 10),
                Bar(date(2026, 8, 3), 60, 100, 50, 80, 10),
                Bar(date(2026, 8, 4), 80, 200, 70, 150, 10)]
        result = candidates(bars, {date(2026, 8, 3)})
        self.assertEqual(result[date(2026, 8, 3)]["peak"], 100)

    def test_all_time_classification_excludes_later_same_month_prices(self):
        bars = [Bar(date(2026, 8, 3), 90, 105, 80, 100, 10),
                Bar(date(2026, 8, 4), 100, 200, 90, 150, 10)]
        months = [Bar(date(2026, 7, 1), 80, 100, 70, 90, 100),
                  Bar(date(2026, 8, 1), 90, 200, 80, 150, 100)]
        self.assertEqual(classify_high(bars, months, date(2026, 8, 3), date(2026, 8, 3)), ("all_time", 105))
        months[0] = Bar(date(2026, 7, 1), 80, 150, 70, 90, 100)
        self.assertEqual(classify_high(bars, months, date(2026, 8, 3), date(2026, 8, 3)), ("52_week", 150))

    def test_same_name_on_different_exchange_or_currency_is_rejected(self):
        row = {"symbol": "LSE:TEST", "exchange": "LSE", "currency": "GBX"}
        payload = {"symbol": "LSE:TEST", "info": {"pro_name": "LSE:TEST", "source_id": "LSE",
                    "currency_code": "GBX", "timezone": "Europe/London"},
                   "bars": [{"timestamp": 1785711600, "open": 90, "high": 110, "low": 80, "close": 100, "volume": 10}]}
        self.assertEqual(len(chart_bars(payload, row)), 1)
        payload["info"]["source_id"] = "SIX"
        with self.assertRaises(chart.ChartHistoryError):
            chart_bars(payload, row)
        payload["info"]["source_id"] = "LSE"
        payload["info"]["currency_code"] = "GBP"
        with self.assertRaisesRegex(chart.ChartHistoryError, "currencies differ"):
            chart_bars(payload, row)

    def test_scanner_stock_label_cannot_override_a_resolved_index(self):
        row = {"symbol": "SIX:SMCI", "exchange": "SIX", "currency": "CHF", "description": "Super Micro Computer, Inc."}
        payload = {"symbol": "SIX:SMCI", "info": {"pro_name": "SIX:SMCI", "source_id": "SIX",
                   "type": "index", "description": "SPI® Mid Total Return Index"}, "bars": []}
        with self.assertRaises(chart.ChartInstrumentError) as caught:
            chart_bars(payload, row)
        self.assertEqual(caught.exception.proof["type"], "index")

    def test_matching_symbol_still_requires_matching_company_name(self):
        row = {"symbol": "EURONEXT:AIR", "exchange": "EURONEXT", "currency": "EUR", "description": "Airbus SE"}
        payload = {"symbol": "EURONEXT:AIR", "info": {"pro_name": "EURONEXT:AIR", "source_id": "EURONEXT",
                   "type": "stock", "description": "Air Liquide SA", "currency_code": "EUR", "timezone": "Europe/Paris"}, "bars": []}
        with self.assertRaisesRegex(chart.ChartHistoryError, "company name"):
            chart_bars(payload, row)

    def test_rate_limit_pauses_new_connections(self):
        class RateLimit(Exception):
            status_code = 429
        fake = SimpleNamespace(create_connection=unittest.mock.Mock(side_effect=RateLimit()))
        chart._paused.clear()
        chart._clients.connection = None
        try:
            with patch.dict(sys.modules, {"websocket": fake}):
                for _ in range(2):
                    with self.assertRaisesRegex(chart.ChartHistoryError, "rate limit"):
                        chart.fetch_chart("XETR:SAP", "1D", 400)
            self.assertEqual(fake.create_connection.call_count, 1)
        finally:
            chart._paused.clear()

    def test_one_closed_exchange_does_not_make_the_whole_european_market_closed(self):
        rows = [{"exchange": exchange} for exchange in ["EURONEXT", "XETR", "LSE", "SIX"]]
        counts = {"EURONEXT": 1, "XETR": 1, "LSE": 0, "SIX": 1}
        validate_session_coverage(date(2026, 8, 31), counts, rows, {"LSE"})
        with self.assertRaises(chart.ChartHistoryError):
            validate_session_coverage(date(2026, 8, 31), counts, rows, set())
        counts["SIX"] = 0
        with self.assertRaises(chart.ChartHistoryError):
            validate_session_coverage(date(2026, 8, 31), counts, rows, {"LSE"})

    def test_cache_captured_before_close_does_not_certify_the_current_session(self):
        self.assertEqual(completed_through(datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)), date(2026, 10, 13))
        self.assertEqual(completed_through(datetime(2026, 10, 14, 17, 0, tzinfo=timezone.utc)), date(2026, 10, 14))

    def test_thin_listing_gap_must_be_proven_by_the_previous_scanner_bar(self):
        row = {"symbol": "LSE:0I0P", "exchange": "LSE", "time": 1791961200, "time[1]": 1788937200}
        bars = [Bar(date(2026, 9, 9), 70, 70, 70, 70, 30)]
        verify_series_end(row, bars, date(2026, 10, 2))
        with self.assertRaises(chart.ChartHistoryError):
            verify_series_end(row, bars, date(2026, 10, 14))
        row["time[1]"] = 1789023600
        with self.assertRaises(chart.ChartHistoryError):
            verify_series_end(row, bars, date(2026, 10, 2))


if __name__ == "__main__":
    unittest.main()
