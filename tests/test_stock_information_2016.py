from pathlib import Path
import sys
import unittest
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_stock_information_2016 as year2016
import backfill_stock_information_2024_h2 as recovery
from backfill_sec_financials_2016 import frame_fact
from extend_stock_history_2023 import join_prices
from backfill_yahoo_calendars import requested_dates
from datetime import date
import refresh_stock_information_history as refresh


class Historical2016Tests(unittest.TestCase):
    def test_monthly_spark_response_is_never_saved_as_daily_history(self):
        import stock_chart_history as charts
        for interval in ["1mo", "3mo"]:
            payload = {"chart": {"result": [{"meta": {"symbol": "AAPL", "dataGranularity": interval}}]}}
            with self.assertRaisesRegex(ValueError, "instead of daily"):
                charts.parse_yahoo(payload, "AAPL")

    def test_duplicate_provider_sessions_are_rejected_before_history_is_saved(self):
        import stock_chart_history as charts
        payload = {"chart": {"result": [{"meta": {"symbol": "AAPL", "instrumentType": "EQUITY", "currency": "USD", "exchangeTimezoneName": "America/New_York"},
            "timestamp": [1451932200, 1451932200], "indicators": {"quote": [{"close": [10, 11]}]}}]}}
        with self.assertRaisesRegex(ValueError, "duplicate or unordered"):
            charts.parse_yahoo(payload, "AAPL")

    def test_denied_network_access_is_not_recorded_as_missing_financials(self):
        from urllib.error import URLError
        denied = URLError(OSError("[WinError 10013] Network access denied"))
        with patch.object(recovery, "resolve_yahoo", return_value="AAPL"), patch.object(recovery.info, "fetch_json", side_effect=denied):
            with self.assertRaises(URLError):
                recovery.fetch({"ticker": "AAPL", "market": "us"})

    def test_2016_report_survives_parser_and_preserves_later_periods(self):
        names = ["START", "END", "STATE", "AUDIT", "TABLE", "COVERAGE_KEY", "FETCHED_KEY", "RESUME"]
        with patch.multiple(recovery, **{name: getattr(recovery, name) for name in names}), patch.object(recovery.info, "START", recovery.info.START):
            year2016.configure()
            payload = {"timeseries": {"result": [{"meta": {"symbol": ["TEST"]},
                "quarterlyTotalRevenue": [{"asOfDate": "2016-03-31", "periodType": "3M", "currencyCode": "TWD", "reportedValue": {"raw": 0}}],
                "quarterlyOperatingIncome": [{"asOfDate": "2016-03-31", "periodType": "3M", "currencyCode": "TWD", "reportedValue": {"raw": -7}}]}]}}
            rows = recovery.info.parse_yahoo_financials(payload, "TEST", "2016-12-31")
            self.assertEqual(len(rows), 1)
            later = {"type": "annual", "period_end": "2017-12-31", "currency": "TWD", "source": "original", "revenue": 12}
            value = recovery.merge({"financials": [later]}, rows, "2026-11-11T00:00:00Z")
            self.assertEqual(value["financials"][0]["revenue"], 0)
            self.assertEqual(value["financials"][0]["operating_income"], -7)
            self.assertIn(later, value["financials"])
            self.assertEqual(value["historical_2016_coverage"]["quarterly_periods"], 1)

    def test_sec_uses_actual_2016_period_and_rejects_ytd_and_other_years(self):
        def fact(start, end):
            return {"start": start, "end": end, "val": -1, "cik": 320193, "accn": "0000320193-17-000001"}
        self.assertEqual(frame_fact(fact("2016-01-01", "2016-03-31"), False)["value"], -1)
        self.assertIsNone(frame_fact(fact("2016-01-01", "2016-06-30"), False))
        self.assertIsNone(frame_fact(fact("2017-01-01", "2017-03-31"), False))

    def test_taiwan_includes_all_three_official_saturdays(self):
        days = requested_dates(date(2016, 1, 1), date(2016, 12, 31), "taiwan")
        for day in [date(2016, 1, 30), date(2016, 6, 4), date(2016, 9, 10)]:
            self.assertIn(day, days)
        self.assertNotIn(date(2016, 2, 27), days)
        for day in [date(2016, 7, 8), date(2016, 9, 27), date(2016, 9, 28)]:
            self.assertNotIn(day, days)

    def test_extension_rejects_incompatible_price_adjustments(self):
        later = {"ticker": "TEST", "currency": "USD", "prices": [["2016-12-27", 10, 9], ["2016-12-28", 11, 10], ["2016-12-29", 12, 11]]}
        older = {**later, "prices": [["2015-12-30", 8, 7], *later["prices"]]}
        self.assertEqual(join_prices(later, older, start="2015-12-20")["prices"], older["prices"])
        bad = {**older, "prices": [[day, close / 2, adjusted / 2] for day, close, adjusted in older["prices"]]}
        self.assertIsNone(join_prices(later, bad, start="2015-12-20"))

    def test_verified_chart_cache_preserves_later_ipo_and_avoids_unnecessary_source_requests(self):
        # TradingView does not return the IPO date. Importing its full curve
        # must retain the confirmed date and keep a 2017 IPO out of 2016 work.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / "state"
            now = datetime.now(timezone.utc).isoformat()
            old = {"ticker": "TEST", "currency": "USD", "source": "Yahoo", "fetched_at": now,
                   "first_trade_date": "2017-01-02", "prices": [["2017-01-02", 10, 10], ["2026-11-10", 20, 20]]}
            payload = {"symbol": "NASDAQ:TEST", "fetched_at": now, "requested_bars": 3200,
                "info": {"pro_name": "NASDAQ:TEST", "source_id": "NASDAQ", "type": "stock",
                         "currency_code": "USD", "timezone": "America/New_York"},
                "bars": [{"timestamp": int(datetime.fromisoformat(day + "T20:00:00+00:00").timestamp()), "close": close}
                         for day, close, _ in old["prices"]]}
            cache = root / "data/tmp_tradingview_chart/1D" / (hashlib.sha256(b"NASDAQ:TEST:1D:3200").hexdigest() + ".json")
            cache.parent.mkdir(parents=True)
            cache.write_text(json.dumps(payload), encoding="utf-8")
            row = {"ticker": "TEST", "exchange": "NASDAQ", "market": "us", "order": 1}
            with patch.object(refresh.information, "ROOT", root), patch.object(refresh.information, "PACKS", root / "info-packs"), \
                 patch.object(refresh.charts, "DATABASE", state / "history.sqlite"), \
                 patch.object(refresh.charts, "PACKS", root / "history-packs"), \
                 patch.object(refresh.charts, "roster", return_value=[row]), \
                 patch.object(refresh.information, "checkpoint"), \
                 patch.object(refresh.information, "fetch_json", side_effect=AssertionError("IPO should not trigger a source request")), \
                 patch.object(refresh, "fallback", side_effect=AssertionError("IPO should not trigger fallback")), \
                 patch.object(sys, "argv", ["refresh", "--state-dir", str(state), "--import-chart-cache", "--extend-to-start"]):
                db = refresh.charts.database()
                db.execute("INSERT INTO history VALUES (?,?)", ("TEST", json.dumps(old)))
                db.commit()
                db.close()
                refresh.main()
                db = refresh.charts.database()
                value = json.loads(db.execute("SELECT value FROM history WHERE ticker='TEST'").fetchone()[0])
                db.close()
            self.assertEqual(value["first_trade_date"], "2017-01-02")
            self.assertEqual(value["prices"], old["prices"])


if __name__ == "__main__":
    unittest.main()
