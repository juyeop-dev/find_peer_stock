from __future__ import annotations

import sys
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_credit_data as credit  # noqa: E402


class CreditDataTests(unittest.TestCase):
    def test_market_balances_are_sorted_and_add_to_total(self) -> None:
        rows = [
            {"TMPV1": "20261012", "TMPV2": 34288699, "TMPV3": 26715212, "TMPV4": 7573487},
            {"TMPV1": "20261008", "TMPV2": 33811321, "TMPV3": 26324143, "TMPV4": 7487178},
        ]
        result = credit.normalize(rows)
        self.assertEqual([row["date"] for row in result], ["2026-10-08", "2026-10-12"])
        self.assertEqual(result[-1]["total"], result[-1]["kospi"] + result[-1]["kosdaq"])

    def test_rejects_mismatched_market_total(self) -> None:
        with self.assertRaisesRegex(ValueError, "do not sum"):
            credit.normalize([{"TMPV1": "20261012", "TMPV2": 100, "TMPV3": 50, "TMPV4": 40}])

    def test_unchanged_incremental_refresh_preserves_generation_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.json"
            published = Path(temp) / "published.json"
            start = datetime(2026, 7, 5)
            history = [{"date": (start + timedelta(days=index)).date().isoformat(),
                        "total": 100, "kospi": 60, "kosdaq": 40} for index in range(100)]
            existing = {"generated_at": "2026-10-12T20:00:00+09:00", "history": history}
            source.write_text(json.dumps(existing), encoding="utf-8")
            with patch.object(credit, "fetch_range", return_value=[] ) as fetch:
                result = credit.generate(datetime(2026, 10, 13, tzinfo=ZoneInfo("Asia/Seoul")), source, published)
            self.assertEqual(result, existing)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(json.loads(published.read_text(encoding="utf-8")), existing)


if __name__ == "__main__":
    unittest.main()
