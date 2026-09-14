from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from localize_korean_new_highs import localize_reports


class KoreanArchiveNamesTests(unittest.TestCase):
    def test_names_are_verified_without_changing_prices_dates_or_authored_descriptions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "reports/korea").mkdir(parents=True)
            (root / "markets.json").write_text(json.dumps({"schema_version": 1, "markets": [{
                "id": "korea", "label": "한국", "timezone": "Asia/Seoul", "default_exchange": "KOSPI",
                "exchanges": [{"id": "KOSPI", "label": "코스피"}],
            }]}), encoding="utf-8")
            original = {"schema_version": 1, "market": "korea", "date": "2026-09-11",
                        "collected_at": "2026-09-13T14:00:00Z", "entries": [{
                            "ticker": "003350.KS", "name": "English Name", "exchange": "KOSPI",
                            "category": "화장품", "high_type": "52_week", "reason": "확인된 사유",
                            "description": "직접 작성한 사업 설명", "change_pct": 19.376899696,
                        }]}
            path = root / "reports/korea/2026-09-11.json"
            path.write_text(json.dumps(original), encoding="utf-8")
            listing = {"name": "한국화장품제조", "exchange": "KOSPI", "source_url": "https://stock.naver.com/"}
            localize_reports(root, fetch_listing=lambda code: listing)
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result["entries"][0]["name"], listing["name"])
            self.assertEqual(result["collected_at"], original["collected_at"])
            for key in ("change_pct", "reason", "description", "high_type", "ticker"):
                self.assertEqual(result["entries"][0][key], original["entries"][0][key])
            first = path.read_bytes()
            localize_reports(root, fetch_listing=lambda code: listing)
            self.assertEqual(path.read_bytes(), first)

            second = copy.deepcopy(original)
            second["date"] = "2026-09-14"
            second["entries"][0]["ticker"] = "999999.KS"
            second_path = root / "reports/korea/2026-09-14.json"
            second_path.write_text(json.dumps(second), encoding="utf-8")
            def failing_listing(code):
                if code == "999999":
                    raise OSError("offline")
                return {**listing, "name": "변경되면 안 되는 이름"}
            with self.assertRaises(OSError):
                localize_reports(root, fetch_listing=failing_listing)
            self.assertEqual(path.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
