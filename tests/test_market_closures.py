from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from market_closures import load_scheduled_closures, merge_closures  # noqa: E402


MARKETS = {"korea", "us", "china", "taiwan", "japan", "europe"}


class MarketClosureTests(unittest.TestCase):
    def test_official_2026_schedule_marks_known_holidays_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        closures = load_scheduled_closures(root / "data" / "market-closures", MARKETS)
        days = {(item["market"], item["date"]) for item in closures}
        self.assertIn(("korea", "2026-10-05"), days)
        self.assertIn(("china", "2026-10-05"), days)
        self.assertIn(("japan", "2026-10-12"), days)
        self.assertNotIn(("us", "2026-10-05"), days)
        self.assertNotIn(("europe", "2026-10-05"), days)

    def test_invalid_or_duplicate_annual_dates_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            calendar = directory / "2026.json"
            payload = {"schema_version": 1, "year": 2026, "markets": [{
                "market": "korea", "source_urls": ["https://example.com/krx"],
                "dates": {"2026-10-03": "주말은 달력에서 자동 처리"},
            }]}
            calendar.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "weekday closure"):
                load_scheduled_closures(directory, MARKETS)
            payload["markets"][0]["dates"] = {"2026-10-05": "개천절 대체공휴일"}
            payload["markets"].append(dict(payload["markets"][0]))
            calendar.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate weekday closure"):
                load_scheduled_closures(directory, MARKETS)

    def test_recorded_session_takes_precedence_over_schedule(self) -> None:
        closure = {"market": "korea", "date": "2026-10-05", "label": "휴장", "reason": "개천절"}
        self.assertEqual(merge_closures([closure], [], [{"market": "korea", "date": "2026-10-05"}]), [])


if __name__ == "__main__":
    unittest.main()
