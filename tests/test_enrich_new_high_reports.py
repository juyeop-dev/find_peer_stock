from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import enrich_new_high_reports as enrich  # noqa: E402


class EnrichNewHighReportsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        self.write(self.source / "markets.json", {
            "schema_version": 1, "markets": [{
                "id": "japan", "label": "일본", "timezone": "Asia/Tokyo", "default_exchange": "all",
                "exchanges": [{"id": "TSE", "label": "도쿄"}],
            }],
        })
        self.report_path = self.source / "reports" / "japan" / "2026-09-14.json"
        self.write(self.report_path, {
            "schema_version": 1, "market": "japan", "date": "2026-09-14",
            "entries": [{
                "ticker": "1000.T", "name": "Test", "exchange": "TSE",
                "category": "Technology", "high_type": "52_week",
                "reason": "신고가 배경 미확인", "description": "Test · Semiconductors",
                "source_symbol": "TSE:1000", "change_pct": 2.5,
            }],
        })

    @staticmethod
    def write(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_enriches_session_prices_and_industry_reason(self) -> None:
        stamp = int(datetime(2026, 9, 14, 6, tzinfo=timezone.utc).timestamp())
        row = {
            "symbol": "TSE:1000", "time": stamp, "open": 100, "close": 110,
            "high": 120, "low": 90, "volume": 1000, "change": 2.5,
            "price_52_week_high": 120, "High.All": 150,
            "currency": "JPY",
        }
        with patch.object(enrich, "scan_historical", return_value=[row]) as scan:
            paths = enrich.enrich_reports(
                self.source, now=datetime(2026, 9, 15, tzinfo=timezone.utc),
            )
        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        self.assertEqual(paths, [self.report_path])
        self.assertEqual(report["entries"][0]["session_open"], 100)
        self.assertEqual(report["entries"][0]["session_close"], 110)
        self.assertEqual(report["entries"][0]["currency"], "JPY")
        self.assertEqual(report["entries"][0]["reason"], "업종: Technology · Semiconductors")
        self.assertEqual(scan.call_args.kwargs["symbols"], {"TSE:1000"})

    def test_missing_historical_symbol_is_recorded_without_inventing_a_price(self) -> None:
        with patch.object(enrich, "scan_historical", return_value=[]):
            enrich.enrich_reports(self.source, now=datetime(2026, 9, 15, tzinfo=timezone.utc))
        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        self.assertNotIn("session_close", report["entries"][0])
        self.assertEqual(report["source_metadata"]["price_enrichment"], {
            "status": "partial", "provider": "TradingView historical screener fields",
            "missing_symbols": ["TSE:1000"],
        })
        self.assertEqual(report["entries"][0]["reason"], "업종: Technology · Semiconductors")

    def test_korean_price_fallback_uses_dated_history_after_delisting(self) -> None:
        entry = {"ticker": "465320.KQ"}
        with patch.object(enrich, "request_with_retry", return_value=[
            ["20260911", 2055, 2140, 2055, 2055, 1170],
        ]):
            prices = enrich.korean_session_prices(entry, date(2026, 9, 11), 30)
        self.assertEqual(prices, (2055, 2055))


if __name__ == "__main__":
    unittest.main()
