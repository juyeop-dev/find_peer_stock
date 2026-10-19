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
    @staticmethod
    def financial(period: str, revenue: float | None, operating_income: float | None, kind: str = "quarterly") -> dict:
        return {"period": period, "type": kind, "revenue": revenue, "operating_income": operating_income, "net_income": None}

    def test_ttm_uses_latest_four_consecutive_standalone_quarters(self) -> None:
        quarters = [self.financial("2026.06.", 473, 138), self.financial("2025.06.", 347, 85),
                    self.financial("2025.12.", 514, 142), self.financial("2026.03.", 280, 92),
                    self.financial("2025.09.", 906, 412)]
        result = semis.build_recent_financials(quarters, [self.financial("2025.12.", 2078, 734, "annual")])
        self.assertEqual(result["basis"], "ttm")
        self.assertEqual((result["revenue"], result["operating_income"]), (2173, 784))
        self.assertEqual(result["period_label"], "2025년 3Q~2026년 2Q")
        self.assertEqual(result["periods"], ["2025.09.", "2025.12.", "2026.03.", "2026.06."])

    def test_ttm_moves_forward_when_next_actual_quarter_is_reported(self) -> None:
        quarters = [self.financial("2025.12.", 100, -20), self.financial("2026.03.", 200, 0),
                    self.financial("2026.06.", 300, 10), self.financial("2026.09.", 400, 30)]
        result = semis.build_recent_financials(quarters, [])
        self.assertEqual(result["period_label"], "2025년 4Q~2026년 3Q")
        self.assertEqual((result["revenue"], result["operating_income"]), (1000, 20))

    def test_ttm_does_not_advance_to_a_consensus_quarter(self) -> None:
        periods = ["202509", "202512", "202603", "202606", "202609"]
        payload = {"financeInfo": {
            "trTitleList": [{"key": period, "title": f"{period[:4]}.{period[4:]}.",
                             "isConsensus": "Y" if period == "202609" else "N"} for period in periods],
            "rowList": [{"title": "매출액", "columns": {period: {"value": "100"} for period in periods}},
                        {"title": "영업이익", "columns": {period: {"value": "10"} for period in periods}}],
        }}
        with patch.object(semis, "fetch_json", return_value=payload):
            quarters = semis.fetch_financials("031980", "quarter")
        result = semis.build_recent_financials(quarters, [])
        self.assertEqual(result["period_label"], "2025년 3Q~2026년 2Q")
        self.assertEqual(result["revenue"], 400)
        self.assertNotIn("2026.09.", result["periods"])

    def test_missing_quarter_uses_explicit_annual_fallback(self) -> None:
        quarters = [self.financial("2025.06.", 10, 1), self.financial("2025.09.", 20, 2),
                    self.financial("2026.03.", 30, 3), self.financial("2026.06.", 40, 4)]
        result = semis.build_recent_financials(quarters, [self.financial("2025.12.", 120, -5, "annual")])
        self.assertEqual(result["basis"], "annual")
        self.assertEqual(result["period_label"], "2025년 연간")
        self.assertEqual((result["revenue"], result["operating_income"]), (120, -5))
        self.assertTrue(result["reason"])

    def test_missing_metric_is_not_zero_or_mixed_with_annual_value(self) -> None:
        quarters = [self.financial("2025.09.", 10, -3), self.financial("2025.12.", 20, 0),
                    self.financial("2026.03.", 30, None), self.financial("2026.06.", 40, 4)]
        result = semis.build_recent_financials(quarters, [self.financial("2025.12.", 200, 50, "annual")])
        self.assertEqual(result["basis"], "ttm")
        self.assertEqual(result["revenue"], 100)
        self.assertIsNone(result["operating_income"])
        self.assertEqual(semis.build_recent_financials([], [])["basis"], "unavailable")

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
        self.assertEqual((len(seeds), len(groups), len(image_tickers)), (102, 28, 65))
        self.assertEqual(sum(bool(group["image"]) for group in groups), 19)
        by_ticker = {seed["ticker"]: seed for seed in seeds}
        self.assertEqual({item["minor"] for item in by_ticker["005930.KS"]["classifications"]},
                         {"IDM", "파운드리", "HBM·AI 메모리", "CXL", "이미지센서·머신비전"})
        self.assertEqual({item["minor"] for item in by_ticker["320000.KQ"]["classifications"]},
                         {"이미지센서·머신비전", "MLCC"})
        self.assertEqual(by_ticker["320000.KQ"]["name"], "한울반도체")
        self.assertEqual({item["minor"] for item in by_ticker["031980.KQ"]["classifications"]},
                         {"장비·검사", "HBM·AI 메모리", "첨단패키징·칩렛"})
        self.assertEqual(by_ticker["319660.KQ"]["minor"], "전공정 장비")
        self.assertEqual(by_ticker["219130.KQ"]["minor"], "PCB·패키지 기판")
        self.assertEqual(by_ticker["141000.KQ"]["minor"], "반도체 장비 개발")

    def test_recent_new_high_additions_have_business_evidence(self) -> None:
        review_path = semis.ROOT / "data" / "semiconductor" / "reviews" / "2026-10-14.json"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        seeds = {row["ticker"]: row for row in semis.classified_seeds()}
        additions = review["additions"]
        self.assertEqual(len({row["ticker"] for row in additions}), 14)
        for row in additions:
            self.assertIn(row["ticker"], seeds)
            self.assertTrue(seeds[row["ticker"]]["business_summary"])
            self.assertTrue(seeds[row["ticker"]]["business_sources"])
            self.assertTrue(all(review["window"]["start"] <= date <= review["window"]["end"]
                                for date in row["new_high_dates"]))
            self.assertTrue(row["new_high_dates"])

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

    def test_recent_naver_prices_fill_yahoo_gap_without_replacing_existing_adjustments(self) -> None:
        history = [{"date": "2026-10-08", "close": 100, "adjusted_close": 50, "volume": 1},
                   {"date": "2026-10-13", "close": 120, "adjusted_close": 60, "volume": 2}]
        recent = [{"date": "2026-10-12", "close": 110, "volume": 3},
                  {"date": "2026-10-13", "close": 121, "volume": 4}]
        result = semis.fill_missing_recent_prices(history, recent)
        self.assertEqual([row["date"] for row in result], ["2026-10-08", "2026-10-12", "2026-10-13"])
        self.assertEqual(result[1], {"date": "2026-10-12", "close": 110, "volume": 3,
                                     "adjusted_close": 55})
        self.assertEqual(result[-1], history[-1])


if __name__ == "__main__":
    unittest.main()
