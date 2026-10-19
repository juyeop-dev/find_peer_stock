from datetime import date
import gzip
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stock_chart_history as charts


class StockChartHistoryTests(unittest.TestCase):
    def test_fresh_utc_daily_values_replace_older_kst_snapshots_for_the_same_session(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE history(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)")
        old = {"ticker":"A","currency":"USD","source":"fixture","requested_range":"2y","fetched_at":"2026-10-20T00:00:00+09:00","prices":[["2025-01-01",100,100],["2026-10-19",100,100]]}
        charts.save_candidate(db,old)
        charts.save_candidate(db,{**old,"fetched_at":"2026-10-19T15:05:00Z","prices":[["2025-01-01",100,100],["2026-10-19",120,120]]})
        self.assertEqual(json.loads(db.execute("SELECT value FROM history").fetchone()[0])["prices"][-1][1],120)
        db.close()

    def test_us_cboe_fallback_requires_same_security_and_is_explicitly_labelled(self):
        payload = {"symbol": "NYSE:EP/PC", "info": {"pro_name": "NYSE:EP/PC", "name": "EP/PC", "full_name": "BATS:EP/PC", "source_id": "BATS", "type": "stock", "currency_code": "USD", "timezone": "America/New_York"}, "bars": [{"timestamp": 1758211200, "close": 10}]}
        self.assertIn("Cboe One", charts.parse_tradingview(payload, "NYSE:EP/PC")["source"])
        payload["info"]["full_name"] = "BATS:OTHER"
        with self.assertRaises(ValueError): charts.parse_tradingview(payload, "NYSE:EP/PC")

    def test_resume_repairs_only_the_pending_stock_and_preserves_completed_results(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = sqlite3.connect(":memory:")
            db.execute("CREATE TABLE history(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)")
            rows = [{"order": i, "ticker": ticker, "name": ticker, "market": "us", "pages": ["peer"]} for i, ticker in enumerate(["A", "B", "C"], 1)]
            def value(ticker):
                return {"ticker": ticker, "currency": "USD", "source": "fixture", "prices": [["2025-10-01", 100, 100], ["2026-10-19", 120, 120]]}
            charts.save_candidate(db, value("A")); charts.save_candidate(db, value("C")); db.commit()
            with patch.object(charts, "AUDIT", root), patch.object(charts, "roster", return_value=rows), patch.object(charts, "database", return_value=db):
                charts.audit(db, rows, date(2026, 10, 19), False, None)
                charts.checkpoint(rows)
                with patch.object(charts, "fetch_live_history", return_value=value("B")) as fetcher, patch.object(sys, "argv", ["stock_chart_history.py", "repair", "--pending-only", "--limit", "1", "--as-of", "2026-10-19"]):
                    charts.main()
                fetcher.assert_called_once_with(rows[1])
                progress = json.loads((root / "progress.json").read_text(encoding="utf-8"))
                self.assertEqual(progress["counts"], {"complete": 3})
                self.assertEqual(progress["pending_count"], 0)
                self.assertEqual(len((root / "results.jsonl").read_text(encoding="utf-8").splitlines()), 3)

    def test_short_or_stale_history_is_not_counted_as_complete(self):
        prices = [[f"2025-11-01", 100, 100]] + [[f"2026-01-{day:02d}", 100, 100] for day in range(1, 29)] + [["2026-10-19", 110, 110]]
        self.assertEqual(charts.assessment({"prices": prices}, date(2026, 10, 19)), "insufficient")
        self.assertEqual(charts.assessment({"prices": prices, "first_trade_date": "2025-11-01"}, date(2026, 10, 19)), "short_listing")
        self.assertEqual(charts.assessment({"prices": prices[:-1]}, date(2026, 10, 19)), "stale")
        self.assertEqual(charts.assessment(None, date(2026, 10, 19)), "missing")

    def test_aliases_do_not_substitute_a_different_listing(self):
        self.assertIsNone(charts.yahoo_symbol("EURONEXT:MC"))
        self.assertEqual(charts.yahoo_symbol("XETR:SAP"), "SAP.DE")
        self.assertEqual(charts.yahoo_symbol("ABR/PF"), "ABR-PF")
        with self.assertRaises(ValueError):
            charts.parse_tradingview({"symbol": "EURONEXT:MC", "info": {"pro_name": "EURONEXT:OTHER"}}, "EURONEXT:MC")

    def test_old_windows_first_trade_dates_and_split_adjustments_are_preserved(self):
        payload = {"chart": {"result": [{"meta": {"symbol": "AAPL", "instrumentType": "EQUITY", "currency": "USD", "exchangeTimezoneName": "America/New_York", "firstTradeDate": -2208988800},
          "timestamp": [1758211200, 1792177200], "indicators": {"quote": [{"close": [100, 120]}], "adjclose": [{"adjclose": [50, 120]}]}}]}}
        result = charts.parse_yahoo(payload, "AAPL")
        self.assertLess(result["first_trade_date"], "1970-01-01")
        self.assertEqual(result["prices"][0][2], 50)
        with self.assertRaises(ValueError):
            charts.parse_yahoo(payload, "MU")

    def test_snapshots_round_trip_without_percent_encoded_filename_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = sqlite3.connect(":memory:")
            db.execute("CREATE TABLE history(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)")
            value = {"ticker": "EURONEXT:MC", "currency": "EUR", "source": "fixture", "prices": [["2025-10-01", 100, 100], ["2026-10-19", 120, 120]]}
            charts.save_candidate(db, value)
            with patch.object(charts, "PACKS", root / "packs"):
                charts.export_packs(db)
                charts.publish(root / "public")
            restored = json.loads((root / "public/EURONEXT~3AMC.json").read_text(encoding="utf-8"))
            self.assertEqual(restored, value)
            charts.save_candidate(db, {**value, "prices": [["2026-10-16", 110, 110], ["2026-10-19", 120, 120]]})
            self.assertEqual(json.loads(db.execute("SELECT value FROM history").fetchone()[0]), value)
            db.close()


if __name__ == "__main__":
    unittest.main()
