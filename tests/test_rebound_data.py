from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rebound_data as source

DAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, 7, tzinfo=timezone.utc)
STAMP = int(datetime(2026, 11, 2, 6, tzinfo=timezone.utc).timestamp())


def row(code="009830", board="KOSPI", **changes):
    values = {"name": code, "description": f"종목 {code}", "exchange": "KRX", "type": "stock", "subtype": "common",
              "close": 108, "low": 100, "change": 0, "market_cap_basic": 5e12, "currency": "KRW", "time": STAMP,
              "indexes": [{"proname": f"KRX:{board}"}], "sector": "산업", "industry": "업종"}
    values.update(changes)
    return {"s": f"KRX:{code}", "d": [values[key] for key in source.COLUMNS]}


def scan(rows=None):
    rows = rows if rows is not None else [row(), row("039030", "KOSDAQ", close=105, market_cap_basic=1e12)]
    return {"totalCount": len(rows), "data": rows}


class ReboundDataTests(unittest.TestCase):
    def test_inclusive_thresholds_flat_stock_and_all_qualifiers_without_top30_limit(self):
        payload = scan([row(), *[row(f"{i:06d}", "KOSDAQ", close=105, market_cap_basic=1e12) for i in range(40)]])
        report = source.report_from_scan(payload, DAY, now=NOW)
        self.assertEqual(len(report["entries"]), 41)
        self.assertAlmostEqual(report["entries"][0]["rebound_pct"], 8)
        self.assertEqual(report["entries"][0]["change_pct"], 0)
        self.assertEqual(report["entries"][1]["exchange"], "KOSDAQ")

    def test_negative_change_small_caps_unrounded_thresholds_and_stale_bars_are_excluded(self):
        payload = scan([row(), row("039030", "KOSDAQ", close=105, market_cap_basic=1e12),
                        row("000001", close=107.9999), row("000002", market_cap_basic=5e12-1),
                        row("000003", change=-0.01), row("000004", time=STAMP-86400),
                        row("000005", market_cap_basic=None), row("000006", change=None), row("000007", indexes=None)])
        result = source.report_from_scan(payload, DAY, now=NOW)
        self.assertEqual(len(result["entries"]), 2)
        for key in ["below_rebound", "below_market_cap", "declining", "stale_session", "missing_market_cap", "missing_change", "unsupported_listing"]:
            self.assertEqual(result["source_metadata"]["excluded"][key], 1)

    def test_missing_or_wrong_daily_low_never_produces_an_empty_success(self):
        for low in [0, -1, None, float("nan"), 109]:
            with self.subTest(low=low), self.assertRaises(ValueError):
                source.report_from_scan(scan([row(low=low), row("039030", "KOSDAQ")]), DAY, now=NOW)

    def test_partial_duplicate_conflicting_or_wrong_session_data_is_rejected(self):
        payload = scan()
        for broken in [{**payload, "totalCount": 3}, scan([row(), row()]), scan([row(indexes=[{"proname": "KRX:KOSPI"}, {"proname": "KRX:KOSDAQ"}])])]:
            with self.assertRaises(ValueError):
                source.report_from_scan(broken, DAY, now=NOW)
        with self.assertRaises(ValueError):
            source.report_from_scan(payload, date(2026, 11, 3), now=NOW)

    def test_zero_results_are_a_recorded_session_and_korean_names_are_used(self):
        report = source.report_from_scan(scan([row(close=101), row("039030", "KOSDAQ", close=101)]), DAY, now=NOW)
        self.assertEqual(report["entries"], [])
        names = source.report_from_scan(scan(), DAY, now=NOW, names={"009830.KS": "한화솔루션"})
        self.assertEqual(names["entries"][0]["name"], "한화솔루션")

    def test_failed_refresh_keeps_saved_history_and_publication_and_same_day_does_not_refetch(self):
        with TemporaryDirectory() as folder:
            source_dir, output = Path(folder) / "source", Path(folder) / "public"
            first = source.collect(source_dir, now=NOW, fetcher=lambda: scan())
            self.assertEqual(first["status"], "updated")
            saved = next(source_dir.rglob("2026-11-02.json")).read_bytes()
            self.assertEqual(source.collect(source_dir, now=NOW, fetcher=lambda: self.fail("Refetched completed day"))["status"], "updated")
            failure = source.collect(source_dir, now=NOW, force=True, fetcher=lambda: {"data": []})
            self.assertEqual(failure["status"], "error")
            self.assertEqual(failure["last_success_date"], "2026-11-02")
            self.assertEqual(next(source_dir.rglob("2026-11-02.json")).read_bytes(), saved)
            index = source.publish(source_dir, output)
            self.assertEqual(index["reports"][0]["count"], 2)
            self.assertTrue((output / "korea/2026_11/2026-11-02.json").exists())

    def test_intraday_and_official_holiday_never_fetch(self):
        with TemporaryDirectory() as folder:
            for now in [datetime(2026, 11, 2, 6, 49, tzinfo=timezone.utc), datetime(2026, 10, 9, 7, tzinfo=timezone.utc)]:
                result = source.collect(Path(folder), now=now, fetcher=lambda: self.fail("Unexpected source fetch"))
                self.assertIn(result["status"], ["pending", "closed"])

    def test_tampered_report_cannot_replace_existing_publication(self):
        report = source.report_from_scan(scan(), DAY, now=NOW)
        with TemporaryDirectory() as folder:
            source_dir, output = Path(folder) / "source", Path(folder) / "public"
            path = source.monthly_report_path(source_dir / "reports", "korea", DAY)
            source.atomic_json(path, report)
            source.publish(source_dir, output)
            previous = (output / "index.json").read_bytes()
            broken = deepcopy(report)
            broken["entries"][0]["rebound_pct"] = 50
            source.atomic_json(path, broken)
            with self.assertRaises(ValueError):
                source.publish(source_dir, output)
            self.assertEqual((output / "index.json").read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
