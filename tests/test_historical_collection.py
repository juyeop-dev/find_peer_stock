from contextlib import ExitStack, redirect_stdout
from dataclasses import replace
from datetime import date, timedelta
import copy
import gzip
import importlib
import io
import json
import os
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collection_request import collection_request, ROOT
from historical_sessions import verified_sessions
from history_policy import DEFAULT_POLICY
from price_history_range import load_price_range
import backfill_credit as credit
import history_jobs as jobs
from run_history import build_plan
import run_history
import fetch_korea_source as korea_source
import backfill_semiconductor_history as semiconductor
import backfill_sector_history_2024 as sectors
import refresh_chart_replay as replay
import backfill_korean_new_highs as korea


class HistoricalCollectionTests(unittest.TestCase):
    def calendar(self, root, year=2014):
        target = root / f"data/market-closures/{year}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / f"data/market-closures/{year}.json").read_bytes())
        return target

    def test_official_sessions_preserve_saturday_and_typhoon_evidence(self):
        days = verified_sessions("2014-01-01", "2014-12-31", "taiwan")
        self.assertEqual(len(days), 248)
        self.assertIn(date(2014, 12, 27), days)
        self.assertNotIn(date(2014, 7, 23), days)
        self.assertEqual(len(verified_sessions("2014-01-01", "2014-12-31", "korea")), 245)

    def test_unknown_or_contradictory_calendar_never_becomes_weekday_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(ValueError, "calendar missing"):
                verified_sessions("2013-01-01", "2013-12-31", "taiwan", root=root)
            path = self.calendar(root)
            value = json.loads(path.read_bytes())
            row = next(row for row in value["markets"] if row["market"] == "taiwan")
            row["dates"]["2014-12-27"] = "conflict"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "both closed and open"):
                verified_sessions("2014-01-01", "2014-12-31", "taiwan", root=root)

    def test_leap_month_and_partial_month_use_distinct_cache_windows(self):
        request = collection_request(year=2016)
        windows = list(credit.month_windows(request))
        self.assertEqual(len(windows), 12)
        self.assertEqual(windows[1][1], date(2016, 2, 29))
        partial = list(credit.month_windows(replace(request, start="2016-02-01", end="2016-02-12")))
        self.assertEqual(partial[0][2].name, "2016-02-01_2016-02-12.json")

    def test_credit_reporting_weekends_and_later_original_values_survive(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            request = collection_request(year=2014, root=root)
            source, public = root / "credit.json", root / "published.json"
            original = {"unit": "KRW million", "source_url": "official", "history": [
                {"date": "2014-01-02", "total": 3, "kospi": 1, "kosdaq": 2},
                {"date": "2015-01-02", "total": 30, "kospi": 10, "kosdaq": 20}]}
            source.write_text(json.dumps(original), encoding="utf-8")
            def fetch(start, end):
                first, last = date(int(start[:4]), int(start[4:6]), int(start[6:])), date(int(end[:4]), int(end[4:6]), int(end[6:]))
                return [{"TMPV1": (day := first + timedelta(days=i)).strftime("%Y%m%d"), "TMPV2": 10, "TMPV3": 4, "TMPV4": 6}
                        for i in range((last - first).days + 1) if (first + timedelta(days=i)).weekday() < 5 or str(first + timedelta(days=i)) == "2014-12-27"]
            stack.enter_context(patch.object(credit.credit, "SOURCE", source))
            stack.enter_context(patch.object(credit.credit, "PUBLISHED", public))
            fetcher = stack.enter_context(patch.object(credit.credit, "fetch_range", side_effect=fetch))
            value = credit.collect(request)
            self.assertEqual(fetcher.call_count, 12)
            self.assertIn(original["history"][0], value["history"])
            self.assertIn(original["history"][1], value["history"])
            self.assertIn("2014-12-27", [row["date"] for row in value["history"]])
            self.assertEqual(value["unit"], original["unit"])
            self.assertEqual(json.loads(public.read_bytes()), value)
            credit.collect(request)
            self.assertEqual(fetcher.call_count, 12)

    def test_bad_credit_month_does_not_change_published_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            request = replace(collection_request(year=2014, root=root), end="2014-01-31")
            source = root / "source.json"
            source.write_bytes(b'{"history":[]}')
            with patch.object(credit.credit, "SOURCE", source), patch.object(credit.credit, "fetch_range", return_value=[{
                "TMPV1": "20150202", "TMPV2": 10, "TMPV3": 4, "TMPV4": 6}]), self.assertRaisesRegex(ValueError, "out-of-range"):
                credit.collect(request)
            self.assertEqual(source.read_bytes(), b'{"history":[]}')

    def test_runner_records_failure_and_retry_without_reusing_wrong_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / "state"
            child = Mock(pid=12345)
            child.wait.side_effect = [7, 0]
            with patch.object(jobs.subprocess, "Popen", return_value=child):
                self.assertEqual(jobs.run_job("credit", ["fixture"], root=root, state=state, identity={"year": 2014}), 7)
                self.assertEqual(jobs.run_job("credit", ["fixture"], root=root, state=state, identity={"year": 2014}), 0)
            value = json.loads((state / "credit.process.json").read_bytes())
            self.assertEqual(value["previous_attempt"]["exit_code"], 7)
            self.assertEqual(value["exit_code"], 0)
            self.assertFalse(list(root.rglob("*.lock")))
            with patch.object(jobs.subprocess, "Popen") as launch, self.assertRaisesRegex(RuntimeError, "not complete for this range"):
                jobs.run_job("sectors", ["fixture"], root=root, state=state, dependencies=["credit"], identity={"year": 2015})
            launch.assert_not_called()

    def test_shared_resource_lease_blocks_duplicate_other_year_without_overwriting_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lock = root / "data/tmp_history_jobs/locks/credit.lock"
            jobs.acquire(lock, {"pid": os.getpid(), "nonce": "existing"})
            with patch.object(jobs.subprocess, "Popen") as launch, self.assertRaises(FileExistsError):
                jobs.run_job("credit", ["fixture"], root=root, state=root / "2015")
            launch.assert_not_called()
            self.assertEqual(json.loads(lock.read_bytes())["nonce"], "existing")
            self.assertFalse((root / "2015/credit.process.json").exists())

    def test_stale_parent_lease_cannot_be_reclaimed_while_child_is_alive(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / "lease.lock"
            lock.write_text(json.dumps({"pid": 123, "child_pid": 456}), encoding="utf-8")
            with patch.object(jobs, "process_alive", side_effect=lambda pid: pid == 456), self.assertRaises(FileExistsError):
                jobs.acquire(lock, {"pid": os.getpid()})
            with patch.object(jobs, "process_alive", return_value=False):
                jobs.acquire(lock, {"pid": os.getpid()})
            self.assertEqual(json.loads(lock.read_bytes())["pid"], os.getpid())

    def test_interrupted_runner_keeps_a_live_child_lease(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            child = Mock(pid=12345)
            child.wait.side_effect = KeyboardInterrupt()
            child.poll.return_value = None
            with patch.object(jobs.subprocess, "Popen", return_value=child), self.assertRaises(KeyboardInterrupt):
                jobs.run_job("credit", ["fixture"], root=root, state=root / "state")
            self.assertTrue((root / "data/tmp_history_jobs/locks/credit.lock").exists())
            self.assertEqual(json.loads((root / "state/credit.process.json").read_bytes())["exit_code"], 130)

    def test_2013_plan_reports_missing_evidence_without_collecting_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            request = collection_request(year=2013, root=root)
            plan = build_plan(request, root=root)
            korea = next(job for job in plan if job["name"] == "korea")
            self.assertTrue(korea["blocked"])
            self.assertIn("2013-01-01", korea["command"])
            self.assertIn("2013-12-31", korea["command"])
            positions = {job["name"]: index for index, job in enumerate(plan)}
            for job in plan:
                for dependency in job["dependencies"]:
                    self.assertLess(positions[dependency], positions[job["name"]])
            self.assertFalse(list(root.iterdir()))

    def test_legacy_job_plans_retain_existing_commands_and_isolated_state(self):
        for year in range(2014, 2019):
            module = importlib.import_module(f"run_{year}")
            output = io.StringIO()
            with redirect_stdout(output), patch.object(jobs.subprocess, "Popen", side_effect=AssertionError("Plan only")):
                module.main(["financials", "--plan"])
            value = json.loads(output.getvalue())
            self.assertEqual(value["range"]["start"], f"{year}-01-01")
            self.assertEqual(value["jobs"]["financials"], module.JOBS["financials"])
            self.assertTrue(value["state"].endswith(f"tmp_{year}"))

    def test_generic_resume_skips_only_matching_success_and_can_explicitly_rerun(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            request = collection_request(year=2014, root=root)
            request.state.mkdir(parents=True)
            command = ["fixture"]
            identity = {"config_sha256": hashlib.sha256(DEFAULT_POLICY.read_bytes()).hexdigest()}
            job = {"name": "financials", "state": str(request.state), "command": command,
                   "identity": identity, "blocked": [], "dependencies": []}
            receipt = {"exit_code": 0, "identity": identity,
                       "command_sha256": hashlib.sha256(json.dumps(command).encode()).hexdigest()}
            path = request.state / "financials.process.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with patch.object(run_history, "collection_request", return_value=request), \
                 patch.object(run_history, "build_plan", return_value=[job]), \
                 patch.object(run_history, "run_job", return_value=0) as run:
                run_history.main(["--execute"])
                run.assert_not_called()
                run_history.main(["--execute", "--rerun-completed"])
                self.assertEqual(run.call_count, 1)
                receipt["exit_code"] = 7
                path.write_text(json.dumps(receipt), encoding="utf-8")
                run_history.main(["--execute"])
                self.assertEqual(run.call_count, 2)

    def test_semiconductor_prefix_keeps_later_history_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            request = collection_request(year=2015, root=root, through_present=True)
            old = {"ticker": "000660.KS", "quote": {"price": 99}, "history": [
                {"date": day, "close": value, "adjusted_close": value, "volume": 1}
                for day, value in [("2016-01-04", 10), ("2016-01-05", 11), ("2016-01-06", 12)]]}
            original = copy.deepcopy(old)
            prices = [["2015-01-02", 9, 9], *[[row["date"], row["close"], row["adjusted_close"]] for row in old["history"]]]
            cache = request.state / "semiconductor/000660.KS.json"
            cache.parent.mkdir(parents=True)
            cache.write_text(json.dumps({"chart": {"result": [{"timestamp": [], "indicators": {"quote": [{"volume": []}]}}]}}), encoding="utf-8")
            with patch.object(semiconductor.semi, "ROOT", root), patch.object(semiconductor.charts, "parse_yahoo", return_value={"currency": "KRW", "prices": prices}):
                result = semiconductor.fetch(old, request)
            self.assertEqual(old, original)
            self.assertEqual(result["history"][1:], old["history"])
            self.assertEqual(result["quote"], old["quote"])
            self.assertEqual(result["historical_2015_extension"]["mode"], "verified_prefix")

    def test_replay_naver_start_follows_verified_calendar_and_request(self):
        request = replace(load_price_range(year=2014), end="2014-01-03")
        raw = '<protocol><chartdata symbol="KOSPI"><item data="20140102|10|12|9|11|1"/><item data="20140103|11|13|10|12|1"/></chartdata></protocol>'
        with patch.object(replay.urllib.request, "urlopen", return_value=io.BytesIO(raw.encode("euc-kr"))):
            result = replay.collect_kospi(request)
        self.assertEqual([bar["date"] for bar in result["bars"]], ["2014-01-02", "2014-01-03"])

    def test_sector_reconstruction_preserves_existing_archive_and_uses_observed_prices(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.calendar(root)
            request = replace(collection_request(year=2014, root=root), start="2014-01-02", end="2014-01-03")
            directory = root / "data/sectors"
            directory.mkdir()
            latest = {"date": "2026-11-18", "source_url": "classification", "stocks": [{"ticker": "000660.KS", "code": "000660", "price": 999, "market_cap": 999999}]}
            (directory / "index.json").write_text(json.dumps(latest), encoding="utf-8")
            reports = root / "data/new-highs/reports/korea"
            reports.mkdir(parents=True)
            for day in ["2014-01-02", "2014-01-03"]:
                (reports / f"{day}.json").write_text("{}")
            old = directory / "daily/2014-01-02.json.gz"
            old.parent.mkdir(); old.write_bytes(b"original archive")
            history = {date(2014, 1, 2): [0, 0, 0, 0, 10, 2], date(2014, 1, 3): [0, 0, 0, 0, 11, 3]}
            with patch.object(sectors, "ROOT", root), patch.object(sectors, "cached_request", return_value={}), \
                 patch.object(sectors, "parse_history", return_value=history), redirect_stdout(io.StringIO()):
                sectors.main(end_before=None, request=request)
            self.assertEqual(old.read_bytes(), b"original archive")
            saved = json.loads(gzip.decompress((directory / "daily/2014-01-03.json.gz").read_bytes()))
            self.assertEqual(saved["stocks"][0]["price"], 11)
            self.assertIsNone(saved["stocks"][0]["market_cap"])

    def test_korean_resume_keeps_existing_report_and_review_but_fills_missing_turnover(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            source, turnover = root / "new-highs", root / "turnover"
            existing = source / "reports/korea/2014-01-02.json"
            existing.parent.mkdir(parents=True); existing.write_bytes(b"original report")
            review = source / "reviews/korea/2014-01-02.json"
            review.parent.mkdir(parents=True); review.write_bytes(b"original review")
            reports = {day: {"entries": [], "date": str(day)} for day in [date(2014, 1, 2), date(2014, 1, 3)]}
            stack.enter_context(patch.object(korea, "TURNOVER_DIR", turnover))
            stack.enter_context(patch.object(korea, "build_reports", return_value=(reports, reports, reports)))
            stack.enter_context(patch.object(korea, "load_markets", return_value=[{"id": "korea", "timezone": "Asia/Seoul"}]))
            stack.enter_context(patch.object(korea, "collection_date", return_value=date(2014, 1, 3)))
            validate = stack.enter_context(patch.object(korea, "validate_report"))
            validate_turnover = stack.enter_context(patch.object(korea, "validate_turnover"))
            stack.enter_context(patch.object(sys, "argv", ["collect", "--start", "2014-01-02", "--end", "2014-01-03",
                                                         "--skip-existing", "--source-dir", str(source)]))
            with redirect_stdout(io.StringIO()):
                korea.main()
            self.assertEqual(existing.read_bytes(), b"original report")
            self.assertEqual(review.read_bytes(), b"original review")
            self.assertEqual(validate.call_count, 1)
            self.assertEqual(validate_turnover.call_count, 2)
            self.assertTrue((source / "reports/korea/2014-01-03.json").exists())
            self.assertTrue(korea.monthly_report_path(turnover / "reports", "korea", date(2014, 1, 2)).exists())

    def test_pinned_krx_cache_preserves_exact_original_and_rejects_changed_checksum(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = b"PAR1original-fixturePAR1"
            with patch.object(korea_source, "urlopen", return_value=io.BytesIO(original)) as fetch:
                value = korea_source.collect(2014, cache_dir=root)
            self.assertEqual(fetch.call_count, 1)
            source = root / "marcap-2014.parquet"
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(value["sha256"], hashlib.sha256(original).hexdigest())
            with patch.object(korea_source, "urlopen", side_effect=AssertionError("Must reuse original")):
                self.assertEqual(korea_source.collect(2014, cache_dir=root), value)
                source.write_bytes(original + b"changed")
                with self.assertRaisesRegex(ValueError, "original retained"):
                    korea_source.collect(2014, cache_dir=root)
            self.assertEqual(source.read_bytes(), original + b"changed")

    def test_unapproved_krx_year_and_incomplete_pair_fail_without_provider_access(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(korea_source, "urlopen", side_effect=AssertionError("No network")):
            root = Path(folder)
            with self.assertRaisesRegex(ValueError, "No approved pinned"):
                korea_source.collect(2013, cache_dir=root)
            source = root / "marcap-2014.parquet"
            source.write_bytes(b"original")
            with self.assertRaisesRegex(ValueError, "both exist"):
                korea_source.collect(2014, cache_dir=root)
            self.assertEqual(source.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
