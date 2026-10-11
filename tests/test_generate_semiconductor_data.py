from __future__ import annotations

import json
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
                        "seed_hash": semis.seed_fingerprint(),
                        "stocks": [{"ticker": "AAA"}]}
            output.write_text(json.dumps(existing), encoding="utf-8")
            result = semis.generate_full(output_path=output,
                now=datetime(2026, 10, 12, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")))
            self.assertEqual(result, existing)

    def test_image_categories_cover_all_stocks_and_repeated_themes(self) -> None:
        seeds = semis.classified_seeds()
        groups = json.loads(semis.CATEGORIES.read_text(encoding="utf-8"))
        image_tickers = {ticker for group in groups for ticker in group["image"]}
        self.assertEqual((len(seeds), len(groups), len(image_tickers)), (82, 19, 65))
        by_ticker = {seed["ticker"]: seed for seed in seeds}
        self.assertEqual({item["minor"] for item in by_ticker["005930.KS"]["classifications"]},
                         {"IDM", "파운드리", "HBM·AI 메모리", "CXL", "이미지센서·머신비전"})
        self.assertEqual({item["minor"] for item in by_ticker["320000.KQ"]["classifications"]},
                         {"이미지센서·머신비전", "MLCC"})
        self.assertEqual(by_ticker["320000.KQ"]["name"], "한울반도체")

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
