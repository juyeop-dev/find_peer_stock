from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_korean_new_highs as backfill  # noqa: E402


class BackfillKoreanNewHighTests(unittest.TestCase):
    def test_requested_dates_skips_weekends_and_rejects_reverse_range(self) -> None:
        self.assertEqual(
            backfill.requested_dates(date(2026, 9, 7), date(2026, 9, 10)),
            [date(2026, 9, day) for day in range(7, 11)],
        )
        with self.assertRaises(ValueError):
            backfill.requested_dates(date(2026, 9, 10), date(2026, 9, 7))

    def test_classification_uses_intraday_high_and_close_direction_filters(self) -> None:
        history = backfill.parse_history([
            ["20260904", 90, 100, 85, 95, 1000],
            ["20260907", 90, 110, 88, 105, 1000],
            ["20260908", 110, 120, 98, 100, 1000],
            ["20260909", 100, 125, 99, 110, 1000],
            ["20260910", 111, 120, 105, 115, 1000],
        ], code="TEST", start=date(2025, 9, 8), end=date(2026, 9, 10))
        result = backfill.classify_window(history, [date(2026, 9, day) for day in range(7, 11)])
        self.assertTrue(result[date(2026, 9, 7)]["passes_close_filter"])
        self.assertFalse(result[date(2026, 9, 8)]["passes_close_filter"])
        self.assertTrue(result[date(2026, 9, 9)]["passes_close_filter"])
        self.assertNotIn(date(2026, 9, 10), result)

    def test_parse_history_rejects_duplicates_and_bad_prices(self) -> None:
        valid = ["20260907", 90, 110, 88, 105, 1000]
        for rows in ([valid, valid], [["bad", 90, 110, 88, 105, 1000]],
                     [["20260907", 90, -1, 88, 105, 1000]]):
            with self.subTest(rows=rows), self.assertRaises(backfill.TradingViewSourceError):
                backfill.parse_history(rows, code="TEST", start=date(2025, 9, 8), end=date(2026, 9, 10))


if __name__ == "__main__":
    unittest.main()
