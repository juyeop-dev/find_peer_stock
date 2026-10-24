"""Validate the persisted financial migration, independently of local caches."""
import gzip
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PersistedKoreaHistoryTests(unittest.TestCase):
    def test_every_migrated_date_has_dated_caps_and_correct_daily_metadata(self):
        audit = json.loads((ROOT / "data/korea-history-recalculation/2026-10-25.json").read_text(encoding="utf-8"))
        self.assertEqual(len(audit["sectors"]), 127)
        self.assertEqual(audit["sector_dates"], 128)
        self.assertEqual(audit["classified_turnover_dates"], 320)
        self.assertEqual(audit["missing_source_dates"], ["2026-10-23"])
        for record in audit["sectors"]:
            snapshot = json.loads(gzip.decompress((ROOT / f"data/sectors/daily/{record['date']}.json.gz").read_bytes()))
            self.assertEqual(snapshot["historical_metrics"]["date"], snapshot["date"])
            matched = [stock for stock in snapshot["stocks"] if stock.get("market_cap_date") == snapshot["date"]]
            self.assertEqual(len(matched), record["matched"])
            self.assertGreaterEqual(len(matched), sum(stock["date"] == snapshot["date"] for stock in snapshot["stocks"]) * .98)
            self.assertTrue(all(stock["market_cap"] > 0 and stock["turnover"] >= 0 for stock in matched))
            if snapshot.get("reconstruction"):
                self.assertTrue(snapshot["reconstruction"]["market_cap_restored"])
        for record in audit["turnover"]:
            if not record["replaced"]:
                continue
            day = record["date"]
            report = json.loads((ROOT / f"data/turnover/reports/korea/{day[:7].replace('-', '_')}/{day}.json").read_text(encoding="utf-8"))
            self.assertEqual(report["source_metadata"]["session"], "daily")
            self.assertNotIn("session_close_at", report["source_metadata"])
            self.assertEqual(sum(e["turnover"] for e in report["entries"]), record["total"])
            self.assertEqual(len(report["entries"]), 30)
            self.assertEqual([e["rank"] for e in report["entries"]], list(range(1, 31)))

    def test_actual_2024_amount_and_cap_replace_the_close_volume_estimate(self):
        snapshot = json.loads(gzip.decompress((ROOT / "data/sectors/daily/2024-07-01.json.gz").read_bytes()))
        samsung = next(stock for stock in snapshot["stocks"] if stock["code"] == "005930")
        self.assertEqual(samsung["price"], 81800)
        self.assertEqual(samsung["market_cap"], 488328212590000)
        self.assertEqual(samsung["turnover"], 925400917400)


if __name__ == "__main__":
    unittest.main()
