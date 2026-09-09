from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import generate_new_high_data as new_highs  # noqa: E402


class NewHighDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.generated = self.root / "generated"
        self.frontend = self.root / "frontend"
        self.markets = {
            "schema_version": 1,
            "markets": [{
                "id": "korea", "label": "한국", "timezone": "Asia/Seoul", "default_exchange": "KOSPI",
                "exchanges": [{"id": "KOSPI", "label": "코스피"}, {"id": "KOSDAQ", "label": "코스닥"}],
            }],
        }
        self.write(self.source / "markets.json", self.markets)
        self.report = {
            "schema_version": 1, "market": "korea", "date": "2026-09-09",
            "category_reasons": {"반도체": "검증용 공통 사유"},
            "sources": [{"label": "검증용 자료", "url": "https://example.com/report"}],
            "entries": [{
                "ticker": "TEST1.KS", "name": "검증용 기업", "exchange": "KOSPI", "category": "반도체",
                "high_type": "all_time", "reason": "검증용 공통 사유", "description": "검증용 기업 설명", "change_pct": 1.5,
            }],
        }

    @staticmethod
    def write(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def write_report(self, payload: dict, market: str = "korea", filename: str | None = None) -> Path:
        path = self.source / "reports" / market / (filename or f"{payload['date']}.json")
        self.write(path, payload)
        return path

    def generate(self) -> dict:
        return new_highs.generate_new_high_data(self.source, self.generated, self.frontend)

    def test_empty_archive_has_markets_and_no_invented_reports(self) -> None:
        index = self.generate()
        self.assertEqual(index, {**self.markets, "reports": []})
        self.assertEqual(list((self.generated / "new-highs").rglob("*.json")),
                         [self.generated / "new-highs" / "index.json"])
        self.assertEqual((self.frontend / "new-highs" / "index.json").read_bytes(),
                         (self.generated / "new-highs" / "index.json").read_bytes())

    def test_daily_append_keeps_history_counts_exchanges_and_peer_data(self) -> None:
        peer_files = [self.generated / "stocks" / "3026.TW.json", self.frontend / "stocks" / "3026.TW.json",
                      self.generated / "index.json", self.frontend / "index.json"]
        for peer_file in peer_files:
            self.write(peer_file, {"sentinel": "existing peer data"})
        initial_bytes = {path: path.read_bytes() for path in peer_files}
        self.write_report(self.report)
        self.generate()
        next_report = copy.deepcopy(self.report)
        next_report["date"] = "2026-09-10"
        next_report["entries"].extend([
            {**self.report["entries"][0], "ticker": "TEST2.KS", "high_type": "52_week"},
            {**self.report["entries"][0], "ticker": "TEST3.KQ", "exchange": "KOSDAQ", "high_type": "52_week"},
        ])
        self.write_report(next_report)
        index = self.generate()
        self.assertEqual([row["date"] for row in index["reports"]], ["2026-09-10", "2026-09-09"])
        latest = index["reports"][0]
        self.assertEqual(latest["counts"], {"total": 3, "high_52_week": 2, "high_all_time": 1})
        self.assertEqual(latest["exchanges"]["KOSPI"], {"total": 2, "high_52_week": 1, "high_all_time": 1})
        self.assertEqual(latest["exchanges"]["KOSDAQ"], {"total": 1, "high_52_week": 1, "high_all_time": 0})
        for destination in (self.generated, self.frontend):
            archived = destination / "new-highs" / "korea" / "2026-09-09.json"
            self.assertEqual(json.loads(archived.read_text(encoding="utf-8")), self.report)
        first_index_bytes = (self.generated / "new-highs" / "index.json").read_bytes()
        self.generate()
        self.assertEqual(first_index_bytes, (self.generated / "new-highs" / "index.json").read_bytes())
        for path, original in initial_bytes.items():
            self.assertEqual(path.read_bytes(), original)

    def test_explicit_empty_report_is_a_recorded_zero_result_day(self) -> None:
        report = {"schema_version": 1, "market": "korea", "date": "2026-09-09", "entries": []}
        self.write_report(report)
        index = self.generate()
        self.assertEqual(len(index["reports"]), 1)
        zero = {"total": 0, "high_52_week": 0, "high_all_time": 0}
        self.assertEqual(index["reports"][0]["counts"], zero)
        self.assertEqual(index["reports"][0]["exchanges"], {"KOSPI": zero, "KOSDAQ": zero})

    def test_invalid_reports_fail_before_changing_published_archive(self) -> None:
        self.write_report(self.report)
        self.generate()
        original = {path: path.read_bytes() for directory in (self.generated, self.frontend) for path in directory.rglob("*.json")}
        cases = [
            ("impossible date", {"date": "2026-02-30"}),
            ("noncanonical date", {"date": "20260910"}),
            ("unknown market", {"market": "unknown"}),
            ("wrong schema", {"schema_version": True}),
            ("entries missing", {"entries": None}),
            ("unsafe URL", {"sources": [{"label": "bad", "url": "javascript:alert(1)"}]}),
            ("relative URL", {"sources": [{"label": "bad", "url": "/report"}]}),
            ("URL credentials", {"sources": [{"label": "bad", "url": "https://user:password@example.com"}]}),
            ("unused category reason", {"category_reasons": {"unknown": "reason"}}),
        ]
        for field, value in [("reason", " "), ("name", ""), ("exchange", "UNKNOWN"),
                             ("high_type", "daily"), ("description", []), ("change_pct", True),
                             ("change_pct", float("nan"))]:
            entry = {**self.report["entries"][0], field: value}
            cases.append((f"invalid {field}: {value}", {"entries": [entry]}))
        cases.append(("duplicate ticker across high types", {"entries": [
            self.report["entries"][0], {**self.report["entries"][0], "ticker": "test1.ks", "high_type": "52_week"},
        ]}))
        for label, updates in cases:
            with self.subTest(label=label):
                report = {**copy.deepcopy(self.report), "date": "2026-09-10", **updates}
                self.write_report(report, filename="2026-09-10.json")
                with self.assertRaises(new_highs.NewHighDataError):
                    self.generate()
                for path, contents in original.items():
                    self.assertEqual(path.read_bytes(), contents)
                self.assertFalse((self.generated / "new-highs" / "korea" / "2026-09-10.json").exists())

    def test_report_folder_and_filename_must_match_payload(self) -> None:
        path = self.write_report(self.report, filename="2026-09-08.json")
        with self.assertRaisesRegex(new_highs.NewHighDataError, "filename"):
            self.generate()
        path.unlink()
        self.write_report(self.report, market="us")
        with self.assertRaisesRegex(new_highs.NewHighDataError, "folder"):
            self.generate()

    def test_new_market_works_from_configuration_without_code_changes(self) -> None:
        self.markets["markets"].append({
            "id": "future-market", "label": "추가 시장", "timezone": "UTC", "default_exchange": "TEST",
            "exchanges": [{"id": "TEST", "label": "검증용 거래소"}],
        })
        self.write(self.source / "markets.json", self.markets)
        report = copy.deepcopy(self.report)
        report["market"] = "future-market"
        report["entries"][0]["exchange"] = "TEST"
        self.write_report(report, market="future-market")
        index = self.generate()
        self.assertEqual(index["reports"][0]["market"], "future-market")
        self.assertTrue((self.frontend / "new-highs" / "future-market" / "2026-09-09.json").is_file())

    def test_invalid_market_configuration_is_rejected(self) -> None:
        for field, value in [("id", "../outside"), ("default_exchange", "UNKNOWN"), ("exchanges", []),
                             ("timezone", "Invalid/Nowhere"), ("timezone", "../Asia/Seoul")]:
            with self.subTest(field=field):
                markets = copy.deepcopy(self.markets)
                markets["markets"][0][field] = value
                self.write(self.source / "markets.json", markets)
                with self.assertRaises(new_highs.NewHighDataError):
                    self.generate()
                self.assertFalse(self.generated.exists())

    def test_all_exchanges_can_be_the_market_default(self) -> None:
        self.markets["markets"][0]["default_exchange"] = "all"
        self.write(self.source / "markets.json", self.markets)
        self.write_report(self.report)
        index = self.generate()
        self.assertEqual(index["markets"][0]["default_exchange"], "all")
        self.assertEqual(set(index["reports"][0]["exchanges"]), {"KOSPI", "KOSDAQ"})

    def test_regular_generator_copies_new_highs_with_peer_data(self) -> None:
        import generate_static_data as stock_data

        self.write_report(self.report)
        args = Namespace(now="2026-09-09T10:00:00+09:00", seed_dir=self.source, company_info_dir=self.source,
                         output_dir=self.generated, frontend_data_dir=self.frontend, new_high_source_dir=self.source,
                         copy_to_frontend=True, no_fetch=True)

        def write_peer_files(*_args, **_kwargs) -> None:
            self.write(self.generated / "stocks" / "3026.TW.json", {"sentinel": "peer stock"})
            self.write(self.generated / "index.json", {"sentinel": "peer index"})

        with (
            patch.object(stock_data, "parse_args", return_value=args),
            patch.object(stock_data, "load_seed_configs", return_value=[]),
            patch.object(stock_data, "load_company_info", return_value={}),
            patch.object(stock_data, "build_catalog", return_value={"companies": {}}),
            patch.object(stock_data, "write_static_data", side_effect=write_peer_files),
        ):
            stock_data.main()
        self.assertEqual(json.loads((self.frontend / "index.json").read_text()), {"sentinel": "peer index"})
        self.assertTrue((self.frontend / "stocks" / "3026.TW.json").is_file())
        self.assertTrue((self.frontend / "new-highs" / "korea" / "2026-09-09.json").is_file())
        index = json.loads((self.frontend / "new-highs" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["reports"][0]["counts"]["high_all_time"], 1)


if __name__ == "__main__":
    unittest.main()
