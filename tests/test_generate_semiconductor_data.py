from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_semiconductor_data as semis  # noqa: E402


class SemiconductorDataTests(unittest.TestCase):
    def test_financials_exclude_consensus_and_keep_actual_values(self) -> None:
        payload = {"financeInfo": {
            "trTitleList": [
                {"key": "202512", "title": "2025.12.", "isConsensus": "N"},
                {"key": "202612", "title": "2026.12.", "isConsensus": "Y"},
            ],
            "rowList": [
                {"title": "매출액", "columns": {"202512": {"value": "12,345"}, "202612": {"value": "99,999"}}},
                {"title": "영업이익", "columns": {"202512": {"value": "-123"}}},
                {"title": "당기순이익", "columns": {"202512": {"value": "-"}}},
            ],
        }}
        with patch.object(semis, "fetch_json", return_value=payload):
            rows = semis.fetch_financials("005930", "annual")
        self.assertEqual(rows, [{"period": "2025.12.", "type": "annual", "revenue": 12345.0,
                                 "operating_income": -123.0, "net_income": None}])

    def test_full_refresh_keeps_existing_snapshot_before_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "index.json"
            existing = {"generated_at": "2026-10-08T16:45:00+09:00",
                        "seed_hash": hashlib.sha256(semis.SEED.read_bytes()).hexdigest(),
                        "stocks": [{"ticker": "AAA"}]}
            output.write_text(json.dumps(existing), encoding="utf-8")
            result = semis.generate_full(output_path=output,
                now=datetime(2026, 10, 12, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")))
            self.assertEqual(result, existing)

    def test_publish_preserves_last_close_when_live_quote_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.json"
            output = Path(temp) / "published.json"
            source.write_text(json.dumps({"generated_at": "2026-10-08T16:45:00+09:00", "stocks": [{
                "ticker": "005930.KS", "code": "005930", "name": "Samsung Electronics",
                "history": [{"date": "2026-10-08", "close": 100, "adjusted_close": 100, "volume": 1000}],
            }]}), encoding="utf-8")
            with patch.object(semis, "fetch_current_quote", side_effect=OSError("offline")):
                result = semis.publish(source, output)
            quote = result["stocks"][0]["quote"]
            self.assertEqual(quote["status"], "stale")
            self.assertEqual(quote["price"], 100)
            self.assertEqual(quote["provider_time"], "2026-10-08")


if __name__ == "__main__":
    unittest.main()
