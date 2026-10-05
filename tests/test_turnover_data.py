from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_turnover_data as turnover  # noqa: E402
from refresh_turnover import refresh_turnover  # noqa: E402


class TurnoverDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source, self.output, self.frontend = root / "source", root / "output", root / "frontend"
        self.write(self.source / "markets.json", {
            "schema_version": 1,
            "markets": [{"id": "korea", "label": "한국", "timezone": "Asia/Seoul", "default_exchange": "all",
                         "exchanges": [{"id": "KOSPI", "label": "코스피"}]}],
        })

    @staticmethod
    def write(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def report(self) -> dict:
        return {"schema_version": 1, "market": "korea", "date": "2026-09-17", "entries": [
            {"rank": 1, "ticker": "005930.KS", "name": "삼성전자", "exchange": "KOSPI", "price": 100000,
             "change_pct": 1.2, "turnover": 2_000_000_000_000, "currency": "KRW", "market_cap": 600_000_000_000_000,
             "sector": "전자 기술", "industry": "반도체", "logo_url": "https://s3-symbol-logo.tradingview.com/samsung--big.svg"},
            {"rank": 2, "ticker": "000660.KS", "name": "SK하이닉스", "exchange": "KOSPI", "price": 300000,
             "change_pct": -0.5, "turnover": 1_000_000_000_000, "currency": "KRW", "market_cap": None,
             "sector": "전자 기술", "industry": "반도체"},
        ]}

    def test_publishes_ranked_archive_and_calendar_summary(self) -> None:
        self.write(self.source / "reports" / "korea" / "2026_09" / "2026-09-17.json", self.report())
        index = turnover.generate_turnover_data(self.source, self.output, self.frontend)
        self.assertEqual(index["reports"][0]["count"], 2)
        self.assertEqual(index["reports"][0]["total_turnover"], 3_000_000_000_000)
        self.assertTrue((self.output / "turnover" / "korea" / "2026_09" / "2026-09-17.json").exists())
        self.assertEqual((self.output / "turnover" / "index.json").read_bytes(),
                         (self.frontend / "turnover" / "index.json").read_bytes())

    def test_official_closure_is_shared_with_turnover_calendar(self) -> None:
        self.write(self.source.parent / "market-closures" / "2026.json", {
            "schema_version": 1, "year": 2026, "markets": [{
                "market": "korea", "source_urls": ["https://example.com/krx"],
                "dates": {"2026-10-05": "개천절 대체공휴일"},
            }],
        })
        index = turnover.generate_turnover_data(self.source, self.output, self.frontend)
        self.assertEqual(index["closures"], [{
            "market": "korea", "date": "2026-10-05", "label": "휴장", "reason": "개천절 대체공휴일",
        }])
        fetch = Mock()
        state = refresh_turnover(
            self.source, now=datetime.fromisoformat("2026-10-05T16:30:00+09:00"),
            market_ids={"korea"}, fetch_report=fetch,
        )
        self.assertEqual(state["markets"]["korea"]["status"], "closed")
        fetch.assert_not_called()

    def test_rejects_rank_gap_and_wrong_sort_order(self) -> None:
        report = self.report()
        report["entries"][1]["rank"] = 3
        self.write(self.source / "reports" / "korea" / "2026_09" / "2026-09-17.json", report)
        with self.assertRaises(turnover.TurnoverDataError):
            turnover.generate_turnover_data(self.source, self.output, self.frontend)
        report["entries"][1]["rank"] = 2
        report["entries"][1]["turnover"] = 3_000_000_000_000
        self.write(self.source / "reports" / "korea" / "2026_09" / "2026-09-17.json", report)
        with self.assertRaises(turnover.TurnoverDataError):
            turnover.generate_turnover_data(self.source, self.output, self.frontend)

    def test_rejects_wrong_month_folder(self) -> None:
        self.write(self.source / "reports" / "korea" / "2026_10" / "2026-09-17.json", self.report())
        with self.assertRaisesRegex(turnover.TurnoverDataError, "month or date"):
            turnover.generate_turnover_data(self.source, self.output, self.frontend)

    def test_refresh_writes_and_reuses_monthly_report(self) -> None:
        calls = []
        def fetch(market: str, session: date) -> dict:
            calls.append((market, session))
            return self.report()
        args = {"target_date": date(2026, 9, 17), "market_ids": {"korea"}, "fetch_report": fetch}
        refresh_turnover(self.source, **args)
        refresh_turnover(self.source, **args)
        self.assertEqual(calls, [("korea", date(2026, 9, 17))])
        self.assertTrue((self.source / "reports" / "korea" / "2026_09" / "2026-09-17.json").exists())

    def test_accepts_period_returns_with_dated_close_basis(self) -> None:
        report = self.report()
        report["entries"][0]["period_returns"] = {
            "1w": {"change_pct": 4.5, "start_date": "2026-09-10", "end_date": "2026-09-17",
                   "basis": "close_to_close"},
        }
        path = self.source / "reports" / "korea" / "2026_09" / "2026-09-17.json"
        self.write(path, report)
        turnover.generate_turnover_data(self.source, self.output, self.frontend)
        published = json.loads((self.output / "turnover" / "korea" / "2026_09" / "2026-09-17.json").read_text(encoding="utf-8"))
        self.assertEqual(published["entries"][0]["period_returns"]["1w"]["change_pct"], 4.5)
        report["entries"][0]["period_returns"]["1w"]["end_date"] = "2026-09-16"
        self.write(path, report)
        with self.assertRaisesRegex(turnover.TurnoverDataError, "report date"):
            turnover.generate_turnover_data(self.source, self.output, self.frontend)

    def test_europe_rejects_tradingview_values_without_usd_units(self) -> None:
        self.write(self.source / "markets.json", {
            "schema_version": 1,
            "markets": [{"id": "europe", "label": "유럽 주요 4거래소", "timezone": "Europe/Paris",
                         "default_exchange": "all", "exchanges": [{"id": "LSE", "label": "런던"}]}],
        })
        report = {"schema_version": 1, "market": "europe", "date": "2026-09-18",
                  "source_metadata": {"provider": "TradingView public scanner"},
                  "entries": [{"rank": 1, "ticker": "LSE:SHEL", "name": "Shell", "exchange": "LSE",
                               "price": 3500, "change_pct": 1, "turnover": 1_000_000,
                               "currency": "GBX", "market_cap": 200_000_000,
                               "sector": "Energy", "industry": "Oil"}]}
        path = self.source / "reports" / "europe" / "2026_09" / "2026-09-18.json"
        self.write(path, report)
        with self.assertRaisesRegex(turnover.TurnoverDataError, "declare USD"):
            turnover.generate_turnover_data(self.source, self.output, self.frontend)
        report["entries"][0].update(turnover_currency="USD", market_cap_currency="USD")
        self.write(path, report)
        index = turnover.generate_turnover_data(self.source, self.output, self.frontend)
        self.assertEqual(index["reports"][0]["currency"], "USD")


if __name__ == "__main__":
    unittest.main()
