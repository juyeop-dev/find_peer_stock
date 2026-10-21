from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stock_information as info
import refresh_stock_information_history as history_refresh


class StockInformationTests(unittest.TestCase):
    def test_live_chart_adapter_without_a_fetch_time_gets_its_actual_receipt_time(self):
        payload = {"symbol":"EURONEXT:MC","info":{"pro_name":"EURONEXT:MC","source_id":"EURONEXT","type":"stock","currency_code":"EUR","timezone":"Europe/Paris"},
                   "requested_bars":550,"bars":[{"timestamp":1735641000,"close":100},{"timestamp":1792393200,"close":120}]}
        with patch("quote_sources.tradingview_chart.fetch_chart", return_value=payload):
            result = history_refresh.tradingview({"ticker":"EURONEXT:MC"})
        self.assertTrue(info.fresh(result["fetched_at"], hours=1))
        self.assertEqual(result["provider_date"], result["prices"][-1][0])

    def test_reported_financials_keep_period_currency_zero_and_exclude_future_and_ytd(self):
        items = [{"asOfDate": day, "periodType": period, "currencyCode": currency, "reportedValue": {"raw": value}}
                 for day, period, currency, value in [("2025-03-31", "3M", "TWD", 0), ("2026-06-30", "3M", "TWD", -10), ("2026-12-31", "3M", "TWD", 100), ("2025-06-30", "6M", "TWD", 20), ("2024-12-31", "3M", "TWD", 40), ("2024-06-30", "3M", "TWD", 50)]]
        payload = {"timeseries": {"result": [{"meta": {"symbol": ["2330.TW"]}, "quarterlyTotalRevenue": items}]}}
        rows = info.parse_yahoo_financials(payload, "2330.TW", "2026-10-20")
        self.assertEqual([(row["period_end"], row["currency"], row["revenue"]) for row in rows], [("2025-03-31", "TWD", 0), ("2026-06-30", "TWD", -10), ("2024-12-31", "TWD", 40)])
        with self.assertRaisesRegex(ValueError, "identity"):
            info.parse_yahoo_financials(payload, "TSM", "2026-10-20")

    def test_naver_excludes_consensus_and_converts_eok_to_won(self):
        payload = {"financeInfo": {"trTitleList": [{"key": "202512", "isConsensus": "N"}, {"key": "202612", "isConsensus": "Y"}],
                                   "rowList": [{"title": "매출액", "columns": {"202512": {"value": "1,234.5"}, "202612": {"value": "2,000"}}},
                                               {"title": "영업이익", "columns": {"202512": {"value": "-5"}}}]}}
        rows = info.parse_naver_financials(payload, "annual", "2026-10-20")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["period_end"], "2025-12-31")
        self.assertEqual(rows[0]["revenue"], 123450000000)
        self.assertEqual(rows[0]["operating_income"], -500000000)
        self.assertEqual(rows[0]["currency"], "KRW")

    def test_exchange_mapping_does_not_guess_a_different_european_listing(self):
        self.assertEqual(info.symbols({"ticker": "EURONEXT:MC"}), ["EURONEXT:MC"])
        self.assertEqual(info.symbols({"ticker": "035420.KS"}), ["KRX:035420"])
        self.assertEqual(info.symbols({"ticker": "0700.HK"}), ["HKEX:700"])
        self.assertEqual(info.symbols({"ticker": "BRK.B", "exchange": "NYSE"}), ["NYSE:BRK.B"])

    def test_scanner_retains_quote_and_financial_currencies_and_marks_old_quote(self):
        raw = {"fetched_at": "2026-10-20T01:00:00+00:00", "row": {"symbol": "NASDAQ:TEST", "close": 25, "change": 0, "time": datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp(), "currency": "USD", "fundamental_currency_code": "TWD", "total_revenue_fy": 900,
                 "fiscal_period_end_fy": datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp()}}
        value = info.scanner_information("TEST", raw, "2026-10-20")
        self.assertEqual(value["quote"]["currency"], "USD")
        self.assertEqual(value["quote"]["status"], "stale")
        self.assertEqual(value["financials"][0]["currency"], "TWD")

    def test_export_publish_roundtrip_and_checkpoint_retains_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = sqlite3.connect(":memory:")
            db.execute("CREATE TABLE information(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)")
            value = {"ticker": "EURONEXT:MC", "fetched_at": "2026-10-20T01:00:00+00:00", "quote": None, "financials": [], "warnings": ["source unavailable"]}
            db.execute("INSERT INTO information VALUES (?,?)", (value["ticker"], json.dumps(value)))
            rows = [{"ticker": "EURONEXT:MC", "order": 1}, {"ticker": "A", "order": 2}]
            with patch.object(info, "ROOT", root), patch.object(info, "PACKS", root / "packs"), patch.object(info, "AUDIT", root / "audit"), patch.object(info, "sync_primary_snapshots"):
                info.export(db); info.publish(); info.checkpoint(db, rows)
                saved = json.loads((root / "frontend/public/data/stock-information/EURONEXT~3AMC.json").read_text(encoding="utf-8"))
                self.assertEqual(saved, value)
                progress = json.loads((root / "audit/progress.json").read_text(encoding="utf-8"))
                self.assertEqual(progress["checked"], 1)
                self.assertEqual(progress["next"]["ticker"], "A")
            db.close()

    def test_freshness_uses_elapsed_time_across_kst_midnight(self):
        self.assertTrue(info.fresh((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()))
        self.assertFalse(info.fresh((datetime.now(timezone.utc) - timedelta(days=2)).isoformat()))

    def test_missing_current_quote_uses_a_dated_real_daily_value_without_claiming_live_success(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE information(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)")
        value = {"ticker": "A", "quote": None, "fetched_at": "2026-10-20T01:00:00+00:00", "warnings": []}
        db.execute("INSERT INTO information VALUES (?,?)", ("A", json.dumps(value))); db.commit()
        history = sqlite3.connect(":memory:")
        history.execute("CREATE TABLE history(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)")
        history.execute("INSERT INTO history VALUES (?,?)", ("A", json.dumps({"ticker":"A","currency":"USD","source":"fixture","fetched_at":"2026-10-19T15:00:00Z","prices":[["2026-09-01",12,12]]})))
        history.commit()
        with patch.object(info.charts, "database", return_value=history):
            info.fill_daily_quotes(db)
        result = json.loads(db.execute("SELECT value FROM information").fetchone()[0])
        self.assertEqual(result["quote"]["price"], 12)
        self.assertEqual(result["quote"]["status"], "stale")
        self.assertEqual(result["quote"]["provider_date"], "2026-09-01")
        self.assertIsNone(result["quote"]["provider_time"])
        self.assertIsNone(result["quote"]["change_pct"])
        db.close()


if __name__ == "__main__":
    unittest.main()
