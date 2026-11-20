from contextlib import ExitStack, redirect_stdout, redirect_stderr
from datetime import date, datetime, timezone
import gzip
import io
import json
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from history_policy import DEFAULT_POLICY
from price_history_range import load_price_range
import extend_stock_history_2023 as extension
import refresh_stock_information_history as refresh
import stock_chart_history as charts
import stock_information as info


class PriceHistoryRangeTests(unittest.TestCase):
    def policy(self, root, year, *, end=None, reference=12):
        value = json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))
        value["collection"].update(start_year=year, end_year=end, price_reference_days=reference)
        path = root / f"policy-{year}-{end}-{reference}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_default_request_preserves_reference_state_and_moving_resume(self):
        request = load_price_range(as_of="2026-11-18")
        self.assertEqual((request.start, request.end, request.reference_start),
                         ("2014-01-01", "2026-11-18", "2013-12-20"))
        self.assertEqual(request.table, "history_2014_updates")
        self.assertEqual(request.storage_start(), "2013-12-20")
        self.assertEqual(request.table, load_price_range(as_of="2026-11-19").table)

    def test_cache_import_receipt_does_not_skip_the_ongoing_price_refresh(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            state = root / "state"
            now = datetime.now(timezone.utc)
            value = {"ticker": "AAPL", "currency": "USD", "source": "original", "prices": [
                ["2014-01-02", 10, 10], [now.date().isoformat(), 20, 20]]}
            for target, name, setting in [(info, "ROOT", root), (info, "AUDIT", root / "audit"),
                                           (info, "PACKS", root / "info-packs"), (charts, "PACKS", root / "history-packs")]:
                stack.enter_context(patch.object(target, name, setting))
            stack.enter_context(patch.object(charts, "roster", return_value=[{"ticker": "AAPL", "order": 1, "market": "us"}]))
            stack.enter_context(patch.object(info, "checkpoint"))
            stack.enter_context(patch.object(charts, "export_packs"))
            db = info.open_database(state)
            db.execute("CREATE TABLE history_2014_updates(ticker TEXT PRIMARY KEY,value TEXT)")
            db.execute("INSERT INTO history_2014_updates VALUES ('AAPL', ?)", (json.dumps({
                "queried_at": now.isoformat(), "updated": True, "cache_status": "overlap_verified"}),))
            db.commit(); db.close()
            payload = {"spark": {"result": [{"symbol": "AAPL", "response": [{}]}]}}
            with patch.object(info, "fetch_json", return_value=payload) as fetch, \
                 patch.object(charts, "parse_yahoo", return_value=value), redirect_stdout(io.StringIO()):
                refresh.main(["--state-dir", str(state)])
                refresh.main(["--state-dir", str(state)])
            self.assertEqual(fetch.call_count, 1)

    def test_year_end_and_reference_window_have_independent_resumable_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            policies = [self.policy(root, 2014), self.policy(root, 2015),
                        self.policy(root, 2014, end=2014), self.policy(root, 2014, reference=20)]
            requests = [load_price_range(path, as_of="2026-11-18") for path in policies]
            self.assertEqual(len({request.table for request in requests}), 4)
            for path, request in zip(policies, requests):
                self.assertEqual(request.table, load_price_range(path, as_of="2026-11-19").table)
            self.assertEqual(requests[2].end, "2014-12-31")
            self.assertEqual(requests[3].reference_start, "2013-12-12")

    def test_recent_policy_retains_the_minimum_two_year_window(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.policy(Path(folder), 2026)
            request = load_price_range(path, as_of="2026-11-18")
            self.assertEqual(request.storage_start(), "2024-11-16")
            self.assertEqual(request.reference_start, "2025-12-20")

    def test_bad_configuration_fails_before_roster_database_or_provider_access(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            path = self.policy(root, 2027)
            for target in [(charts, "roster"), (charts, "database"), (info, "open_database"), (info, "fetch_json")]:
                stack.enter_context(patch.object(*target, side_effect=AssertionError("Must fail before access")))
            for run in [lambda: refresh.main(["--history-config", str(path)]),
                        lambda: extension.main(["--history-config", str(path)])]:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    run()
                self.assertEqual(caught.exception.code, 2)
            self.assertEqual(list(root.iterdir()), [path])

    def test_dry_run_legacy_commands_have_no_data_access(self):
        with patch.object(charts, "database", side_effect=AssertionError("No database")), \
             patch.object(charts, "roster", side_effect=AssertionError("No roster")):
            output = io.StringIO()
            with redirect_stdout(output):
                extension.main(["--dry-run"], year=2014, cache_years=(2014,))
            result = json.loads(output.getvalue())
            self.assertEqual(result["state_table"], "history_2014_updates")
            self.assertEqual(result["cache_years"], [2014])
            self.assertTrue(result["state_dir"].endswith("tmp_2014_history"))
            self.assertEqual(result["price_reference_start"], "2013-12-20")
            output = io.StringIO()
            with redirect_stdout(output):
                refresh.main(["--dry-run", "--state-dir", "folder with spaces", "--exclude-market", "korea"])
            result = json.loads(output.getvalue())
            self.assertEqual(result["state_table"], "history_2014_updates")
            self.assertIn('--state-dir "folder with spaces"', result["resume"])
            self.assertIn("--exclude-market korea", result["resume"])
            self.assertNotIn("--dry-run", result["resume"])

    def test_all_annual_entry_points_pass_their_year_without_global_mutation(self):
        previous_start, previous_database = info.START, charts.DATABASE
        for year in range(2014, 2023):
            with patch.object(extension, "main") as main:
                runpy.run_path(str(DEFAULT_POLICY.parents[1] / f"scripts/extend_stock_history_{year}.py"), run_name="__main__")
                main.assert_called_once_with(**({"year": year, "cache_years": (2014,)} if year == 2014 else {"year": year}))
        self.assertEqual((info.START, charts.DATABASE), (previous_start, previous_database))

    def test_yahoo_dated_request_uses_the_explicit_window_and_exclusive_end(self):
        request = load_price_range(year=2014, as_of="2026-11-18")
        original = {"ticker": "AAPL", "currency": "USD", "prices": [
            ["2000-01-03", 1, 1], ["2014-01-02", 10, 9], ["2014-12-31", 11, 10], ["2026-11-18", 20, 19]]}
        with patch.object(info, "fetch_json", return_value={}) as fetch, \
             patch.object(charts, "parse_yahoo", return_value=original):
            value = refresh.fallback({"ticker": "AAPL", "market": "us"}, request=request)
        params = parse_qs(urlparse(fetch.call_args.args[0]).query)
        self.assertEqual(datetime.fromtimestamp(int(params["period1"][0]), timezone.utc).date().isoformat(), request.storage_start())
        self.assertEqual(datetime.fromtimestamp(int(params["period2"][0]), timezone.utc).date(), date(2015, 1, 1))
        self.assertEqual(value["prices"], original["prices"][1:3])
        self.assertEqual(value["requested_end"], "2014-12-31")
        self.assertEqual(len(original["prices"]), 4)

    def test_naver_fallback_receives_the_same_explicit_dates(self):
        request = load_price_range(year=2015, as_of="2026-11-18")
        bars = {date(2015, 1, 2): [0, 0, 0, 0, 10], date(2015, 12, 30): [0, 0, 0, 0, 11]}
        with patch.object(info, "fetch_json", side_effect=ValueError("Yahoo has no listing")), \
             patch("backfill_korean_new_highs.cached_request", return_value=b"original"), \
             patch("backfill_korean_new_highs.history_url", return_value="fixture") as url, \
             patch("backfill_korean_new_highs.parse_history", return_value=bars) as parse:
            value = refresh.fallback({"ticker": "000660.KS", "market": "korea"}, request=request)
        url.assert_called_once_with("000660", date.fromisoformat(request.storage_start()), date(2015, 12, 31))
        self.assertEqual(parse.call_args.kwargs["end"], date(2015, 12, 31))
        self.assertEqual(value["prices"], [["2015-01-02", 10, 10], ["2015-12-30", 11, 11]])

    def test_tradingview_keeps_provider_cap_and_filters_completed_year(self):
        request = load_price_range(year=2014, as_of="2026-11-18")
        original = {"ticker": "EURONEXT:MC", "currency": "EUR", "prices": [
            ["2014-01-02", 10, 10], ["2014-12-31", 11, 11], ["2026-11-18", 20, 20]]}
        with patch("quote_sources.tradingview_chart.fetch_chart", return_value={}) as fetch, \
             patch.object(charts, "parse_tradingview", return_value=original):
            value = refresh.tradingview({"ticker": "EURONEXT:MC"}, request)
        count = fetch.call_args.args[2]
        self.assertTrue(550 <= count <= 5000)
        self.assertEqual(value["prices"], original["prices"][:2])
        with self.assertRaisesRegex(ValueError, "requested range"):
            request.bound({"prices": original["prices"][2:]})

    def test_later_listing_decision_uses_its_own_request(self):
        value = {"first_trade_date": "2015-01-02", "prices": [["2015-03-02", 10, 10]]}
        first = load_price_range(year=2014, as_of="2026-11-18")
        second = load_price_range(year=2015, as_of="2026-11-18")
        self.assertFalse(refresh.needs_historical_extension(value, first))
        self.assertTrue(refresh.needs_historical_extension(value, second))

    def test_checkpoint_uses_explicit_range_state_and_retains_default_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            request = load_price_range(year=2015, as_of="2026-11-18")
            db = sqlite3.connect(":memory:")
            history = sqlite3.connect(":memory:")
            db.execute("CREATE TABLE information(ticker TEXT PRIMARY KEY,value TEXT)")
            db.execute("CREATE TABLE financial_2025_updates(ticker TEXT PRIMARY KEY,value TEXT)")
            db.execute("CREATE TABLE history_2014_updates(ticker TEXT PRIMARY KEY,value TEXT)")
            db.execute(f"CREATE TABLE {request.table}(ticker TEXT PRIMARY KEY,value TEXT)")
            db.execute("INSERT INTO information VALUES ('A', '{}')")
            db.execute("INSERT INTO financial_2025_updates VALUES ('A', '{}')")
            db.execute("INSERT INTO history_2014_updates VALUES ('A', '{}')")
            history.execute("CREATE TABLE history(ticker TEXT PRIMARY KEY,value TEXT)")
            history.execute("INSERT INTO history VALUES ('A', ?)", (json.dumps({"prices": [
                ["2014-12-22", 10, 10], ["2015-12-31", 11, 11]]}),))
            default_audit = root / "audit"
            default_audit.mkdir()
            original = b'{"original":true}'
            (default_audit / "progress.json").write_bytes(original)
            scoped = default_audit / "price-ranges" / request.scope
            with patch.object(info, "AUDIT", default_audit):
                info.checkpoint(db, [{"ticker": "A", "order": 1}], history,
                                history_request=request, history_resume="custom resume command", audit_dir=scoped)
            progress = json.loads((scoped / "progress.json").read_bytes())
            self.assertEqual(progress["requested_start"], "2015-01-01")
            self.assertEqual(progress["requested_end"], "2015-12-31")
            self.assertEqual(progress["stages"]["daily_history"]["checked"], 0)
            self.assertEqual(progress["resume"], "custom resume command")
            self.assertEqual(progress["history_counts"], {"complete": 1})
            self.assertEqual((default_audit / "progress.json").read_bytes(), original)
            db.close(); history.close()

    def test_cache_imports_in_one_process_preserve_prices_metadata_and_year_state(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            state = root / "state"
            old = {"ticker": "AAPL", "currency": "USD", "source": "existing", "quote": {"price": 99},
                   "prices": [["2016-01-04", 10, 10], ["2016-01-05", 11, 11], ["2016-01-06", 12, 12], ["2026-11-18", 99, 99]]}
            candidates = {2015: {**old, "prices": [["2015-01-02", 9, 9], *old["prices"]]},
                          2014: {**old, "prices": [["2014-01-02", 8, 8], ["2015-01-02", 9, 9], *old["prices"]]}}
            cache = root / "cache.json"
            cache.write_text("{}", encoding="utf-8")
            for target, name, value in [(info, "ROOT", root), (info, "AUDIT", root / "audit"),
                                         (info, "PACKS", root / "info-packs"), (charts, "PACKS", root / "history-packs")]:
                stack.enter_context(patch.object(target, name, value))
            stack.enter_context(patch.object(charts, "roster", return_value=[{"ticker": "AAPL", "order": 1}]))
            stack.enter_context(patch.object(extension, "cached_yahoo_path", return_value=cache))
            original_database = charts.DATABASE
            db = charts.database(state / "history.sqlite")
            db.execute("INSERT INTO history VALUES (?,?)", ("AAPL", json.dumps(old)))
            db.commit(); db.close()
            for year in [2015, 2014]:
                with patch.object(charts, "parse_yahoo", return_value=candidates[year]), redirect_stdout(io.StringIO()):
                    extension.main(["--state-dir", str(state)], year=year, cache_years=(year,))
            db = charts.database(state / "history.sqlite")
            value = json.loads(db.execute("SELECT value FROM history").fetchone()[0]); db.close()
            self.assertEqual(value["prices"], candidates[2014]["prices"])
            self.assertEqual(value["quote"], old["quote"])
            self.assertEqual(value["source"], old["source"])
            self.assertIn("historical_2014_extension", value)
            self.assertIn("historical_2015_extension", value)
            self.assertEqual(charts.DATABASE, original_database)
            db = sqlite3.connect(state / "information.sqlite")
            for year in [2014, 2015]:
                self.assertEqual(db.execute(f"SELECT count(*) FROM history_{year}_updates").fetchone()[0], 1)
            db.close()

    def test_refresh_resume_does_not_reuse_other_ranges_or_modify_original_packs(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            state = root / "state"
            packs = root / "history-packs"
            packs.mkdir()
            old = {"ticker": "AAPL", "currency": "USD", "source": "original", "prices": [["2026-11-18", 99.123456789, 98.987654321]]}
            raw = gzip.compress(json.dumps({"AAPL": old}).encode())
            source = packs / "a.json.gz"
            source.write_bytes(raw)
            policies = [self.policy(root, year, end=year) for year in [2014, 2015]]
            for target, name, value in [(info, "ROOT", root), (info, "AUDIT", root / "audit"),
                                         (info, "PACKS", root / "info-packs"), (charts, "PACKS", packs)]:
                stack.enter_context(patch.object(target, name, value))
            stack.enter_context(patch.object(charts, "roster", return_value=[{"ticker": "AAPL", "order": 1, "market": "us"}]))
            stack.enter_context(patch.object(charts, "export_packs"))
            payload = {"spark": {"result": [{"symbol": "AAPL", "response": [{}]}]}}
            fetch = stack.enter_context(patch.object(info, "fetch_json", return_value=payload))
            original_database = charts.DATABASE
            for path in policies + policies:
                candidate = {**old, "prices": [["2013-01-02", 5, 5], ["2014-01-02", 8, 8], ["2014-12-31", 9, 9], ["2015-12-31", 10, 10], *old["prices"]]}
                with patch.object(charts, "parse_yahoo", return_value=candidate), redirect_stdout(io.StringIO()):
                    refresh.main(["--history-config", str(path), "--state-dir", str(state)])
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(source.read_bytes(), raw)
            self.assertEqual(charts.DATABASE, original_database)
            db = charts.database(state / "history.sqlite")
            value = json.loads(db.execute("SELECT value FROM history").fetchone()[0]); db.close()
            self.assertIn(old["prices"][0], [p for snapshot in [value, *value.get("prior_snapshots", [])] for p in snapshot["prices"]])
            db = sqlite3.connect(state / "information.sqlite")
            for path in policies:
                request = load_price_range(path)
                self.assertEqual(db.execute(f"SELECT count(*) FROM {request.table}").fetchone()[0], 1)
                audit = json.loads((root / "audit" / f"history-{request.scope}-progress.json").read_bytes())
                self.assertEqual(audit["requested_start"], request.start)
                self.assertIn('--history-config "', audit["resume"])
                checkpoint = json.loads((root / "audit" / "price-ranges" / request.scope / "progress.json").read_bytes())
                self.assertEqual(checkpoint["stages"]["daily_history"]["checked"], 1)
            db.close()


if __name__ == "__main__":
    unittest.main()
