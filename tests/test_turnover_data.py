from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_turnover_data as turnover  # noqa: E402


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
        self.write(self.source / "reports" / "korea" / "2026-09-17.json", self.report())
        index = turnover.generate_turnover_data(self.source, self.output, self.frontend)
        self.assertEqual(index["reports"][0]["count"], 2)
        self.assertEqual(index["reports"][0]["total_turnover"], 3_000_000_000_000)
        self.assertTrue((self.output / "turnover" / "korea" / "2026-09-17.json").exists())
        self.assertEqual((self.output / "turnover" / "index.json").read_bytes(),
                         (self.frontend / "turnover" / "index.json").read_bytes())

    def test_rejects_rank_gap_and_wrong_sort_order(self) -> None:
        report = self.report()
        report["entries"][1]["rank"] = 3
        self.write(self.source / "reports" / "korea" / "2026-09-17.json", report)
        with self.assertRaises(turnover.TurnoverDataError):
            turnover.generate_turnover_data(self.source, self.output, self.frontend)
        report["entries"][1]["rank"] = 2
        report["entries"][1]["turnover"] = 3_000_000_000_000
        self.write(self.source / "reports" / "korea" / "2026-09-17.json", report)
        with self.assertRaises(turnover.TurnoverDataError):
            turnover.generate_turnover_data(self.source, self.output, self.frontend)


if __name__ == "__main__":
    unittest.main()
