from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from recalculate_korea_history import daily_turnover, enrich_sector, normalize_row


class KoreanHistoricalRecalculationTests(unittest.TestCase):
    def raw(self, code="005930", **changes):
        return {"Code": code, "Name": "한국 종목", "Market": "KOSPI", "Close": 100,
                "ChangesRatio": -1, "Volume": 200, "Amount": 19876, "Marcap": 100000,
                "Stocks": 1000, **changes}

    def test_won_units_are_verified_against_dated_price_and_shares(self):
        row = normalize_row(self.raw())
        self.assertEqual(row["market_cap"], 100000)
        self.assertEqual(row["turnover"], 19876)
        with self.assertRaisesRegex(ValueError, "unit/share"):
            normalize_row(self.raw(Marcap=0.1))
        self.assertIsNone(normalize_row(self.raw(Market="KONEX")))
        self.assertIsNone(normalize_row(self.raw(Close=0)))

    def test_dated_caps_and_actual_amounts_preserve_original_adjusted_returns(self):
        returns = {"day": 2, "week": 3, "month": 4, "quarter": 5, "year": 6}
        snapshot = {"date": "2024-07-01", "stocks": [{"code": "005930", "ticker": "005930.KS",
            "date": "2024-07-01", "price": 50, "returns": returns, "market_cap": None, "turnover": 20000}],
            "reconstruction": {"note": "old estimate"}}
        result = enrich_sector(snapshot, {"005930": normalize_row(self.raw())}, {"revision": "fixture", "sha256": "fixture"})
        self.assertEqual(result["stocks"][0]["price"], 50)
        self.assertEqual(result["stocks"][0]["returns"], returns)
        self.assertEqual(result["stocks"][0]["market_cap"], 100000)
        self.assertEqual(result["stocks"][0]["turnover"], 19876)
        self.assertEqual(result["stocks"][0]["market_cap_date"], "2024-07-01")
        self.assertTrue(result["reconstruction"]["market_cap_restored"])
        self.assertIsNone(snapshot["stocks"][0]["market_cap"])

    def test_missing_historical_cap_never_uses_a_current_value(self):
        snapshot = {"date": "2024-07-01", "stocks": [{"code": "005930", "ticker": "005930.KS",
            "date": "2024-07-01", "market_cap": None}]}
        with self.assertRaisesRegex(ValueError, "coverage"):
            enrich_sector(snapshot, {}, {"revision": "fixture", "sha256": "fixture"})

    def test_top_thirty_uses_actual_amount_not_close_times_volume_or_old_membership(self):
        rows = {f"{i:06}": normalize_row(self.raw(f"{i:06}", Amount=i + 1, Volume=999999-i)) for i in range(35)}
        report = {"market": "korea", "date": "2024-07-01", "entries": [{"ticker": "000000.KS", "sector": "Old", "industry": "Old"}]}
        result = daily_turnover(report, rows, {"revision": "fixture", "sha256": "fixture"}, {})
        self.assertEqual(len(result["entries"]), 30)
        self.assertEqual(result["entries"][0]["ticker"], "000034.KS")
        self.assertEqual(result["entries"][0]["turnover"], 35)
        self.assertEqual(result["entries"][-1]["ticker"], "000005.KS")
        self.assertEqual(result["source_metadata"]["session"], "daily")
        self.assertNotIn("session_close", result["source_metadata"])
        self.assertNotIn("session_close_at", result["source_metadata"])
        self.assertEqual(result["entries"][0]["market_cap_currency"], "KRW")


if __name__ == "__main__":
    unittest.main()
