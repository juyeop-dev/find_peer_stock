from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import generate_static_data as data_gen  # noqa: E402


class GenerateStaticDataTests(unittest.TestCase):
    def test_pre_open_reuses_previous_quote_even_when_force_fetching(self) -> None:
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

        with patch.object(data_gen, "fetch_quote", side_effect=AssertionError("should not fetch")):
            snapshot = data_gen.build_quote_snapshot(
                "2303.TW",
                generated_at=generated_at,
                no_fetch=False,
                force_fetch=True,
                previous_quote=previous_quote,
            )

        self.assertEqual(snapshot["price"], 111.0)
        self.assertEqual(snapshot["change"], 1.0)
        self.assertEqual(snapshot["change_pct"], 0.9090909090909091)
        self.assertEqual(snapshot["refresh_status"], "pre_open_reused")
        self.assertEqual(snapshot["last_checked_at"], generated_at.isoformat())
        self.assertEqual(snapshot["market_status"], "closed")
        self.assertIn("before regular session open", snapshot["market_status_reason"])


if __name__ == "__main__":
    unittest.main()
