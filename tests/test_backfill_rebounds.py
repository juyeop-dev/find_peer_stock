from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_rebounds as source
from rebound_data import publish

DAY = date(2018, 1, 2)
INFO = {"year": 2018, "revision": "a" * 40, "sha256": "b" * 64,
        "fetched_at": "2026-11-05T08:00:00+00:00", "url": "https://example.com/original.parquet"}


def row(code="009830", board="KOSPI", **changes):
    value = {"Date": datetime(2018, 1, 2), "Code": code, "Name": "당시 종목명",
             "Market": board, "Close": 108, "Low": 100, "ChangesRatio": 0,
             "Volume": 1000, "Amount": 108000, "Marcap": 5_400_000_000_000,
             "Stocks": 50_000_000_000}
    value.update(changes)
    return value


def report(rows=None):
    return source.report_from_rows(rows if rows is not None else [row(), row("039030", "KOSDAQ", Close=105, Marcap=5_250_000_000_000)],
                                   DAY, INFO, minimum_symbols=2)


class HistoricalReboundsTests(unittest.TestCase):
    def test_dated_unadjusted_values_include_historical_listing_without_current_roster(self):
        result = report()
        self.assertEqual([entry["ticker"] for entry in result["entries"]], ["009830.KS", "039030.KQ"])
        self.assertEqual(result["entries"][0]["market_cap_date"], "2018-01-02")
        self.assertEqual(result["entries"][0]["market_cap"], 5_400_000_000_000)
        self.assertAlmostEqual(result["entries"][0]["rebound_pct"], 8)
        self.assertEqual(result["source_metadata"]["source_sha256"], INFO["sha256"])
        self.assertEqual(result["source_metadata"]["fetched_at"], INFO["fetched_at"])

    def test_preferred_konex_suspended_declining_and_small_caps_are_excluded(self):
        result = report([row(), row("039030", "KOSDAQ"), row("005935"), row("000010", "KONEX"),
                         row("000020", Volume=0, Low=0), row("000030", ChangesRatio=-.01),
                         row("000040", Stocks=1, Marcap=108)])
        self.assertEqual(len(result["entries"]), 2)
        self.assertEqual(result["source_metadata"]["excluded"],
                         {"unsupported_listing": 2, "no_trading": 1, "declining": 1, "below_market_cap": 1})

    def test_invalid_low_wrong_date_duplicate_and_wrong_capitalization_units_fail(self):
        for change in [{"Low": 0}, {"Low": 109}, {"Low": None}, {"Marcap": 5_400_000},
                       {"Date": datetime(2018, 1, 3)}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                report([row(**change), row("039030", "KOSDAQ")])
        with self.assertRaises(ValueError):
            report([row(), row()])

    def test_partial_universe_or_missing_board_cannot_be_saved_as_zero(self):
        with self.assertRaises(ValueError):
            report([row()])
        with self.assertRaises(ValueError):
            report([row(), row("000020")])
        with self.assertRaises(ValueError):
            source.report_from_rows([row(), row("039030", "KOSDAQ")], DAY, INFO)
        result = report([row(Low=108), row("039030", "KOSDAQ", Low=108)])
        self.assertEqual(result["entries"], [])

    def test_full_batch_validation_precedes_writes_and_existing_success_is_preserved(self):
        with TemporaryDirectory() as folder:
            output = Path(folder)
            original = report()
            broken = deepcopy(original)
            broken["entries"][0]["rebound_pct"] = 100
            with self.assertRaises(ValueError):
                source.restore_reports([original, broken], output)
            self.assertEqual(list(output.rglob("*.json")), [])
            self.assertEqual(source.restore_reports([original], output), 1)
            path = next(output.rglob("2018-01-02.json"))
            saved = path.read_bytes()
            different = report([row(), row("039030", "KOSDAQ", Low=108)])
            self.assertEqual(source.restore_reports([different], output), 0)
            self.assertEqual(path.read_bytes(), saved)
            index = publish(output, output / "public")
            self.assertEqual(index["reports"][0]["date"], "2018-01-02")
            self.assertEqual(index["reports"][0]["count"], 2)

    def test_checksum_and_source_revision_are_verified_before_reading(self):
        import hashlib
        with TemporaryDirectory() as folder:
            path = Path(folder) / "marcap-2018.parquet"
            raw = b"original data"
            path.write_bytes(raw)
            info = {**INFO, "sha256": hashlib.sha256(raw).hexdigest(),
                    "url": f"https://raw.githubusercontent.com/FinanceData/marcap/{INFO['revision']}/data/{path.name}"}
            path.with_suffix(".source.json").write_text(json.dumps(info), encoding="utf-8")
            self.assertEqual(source.verified_source(path), info)
            path.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                source.verified_source(path)


if __name__ == "__main__":
    unittest.main()
