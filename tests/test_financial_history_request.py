from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from dataclasses import replace
import copy
import gzip
import importlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stock_information as info
import stock_chart_history as charts
import backfill_stock_information_2024_h2 as recovery
from financial_history_request import financial_request
from history_policy import DEFAULT_POLICY


def statement(year, *, currency="USD", revenue=0):
    return {"type": "annual", "period_end": f"{year}-12-31", "currency": currency,
            "source": "original", "revenue": revenue, "operating_income": -7}


class FinancialHistoryRequestTests(unittest.TestCase):
    def test_named_contexts_preserve_paths_and_do_not_mutate_each_other(self):
        baseline = info.START
        requests = [importlib.import_module(f"backfill_stock_information_{year}").configure()
                    for year in [2014, 2024, 2015, 2014]]
        self.assertEqual(requests[0], requests[3])
        for request, year in zip(requests, [2014, 2024, 2015, 2014]):
            self.assertEqual(request.table, f"financial_{year}_updates")
            self.assertEqual(request.state.name, f"tmp_{year}")
            self.assertEqual(request.coverage_key, f"historical_{year}_coverage")
        self.assertEqual(info.START, baseline)
        half = recovery.default_request()
        self.assertEqual((half.start, half.table, half.audit.name),
                         ("2024-07-01", "financial_2024_h2_updates", "2024-h2"))
        self.assertEqual(financial_request(year=2013).resume,
                         "python -u scripts/backfill_stock_information.py collect --year 2013")

    def test_parsers_accept_explicit_earlier_year_without_global_changes(self):
        row = {"asOfDate": "2013-03-31", "periodType": "3M", "currencyCode": "USD", "reportedValue": {"raw": 0}}
        payload = {"timeseries": {"result": [{"meta": {"symbol": ["A"]}, "quarterlyTotalRevenue": [row]}]}}
        self.assertEqual(info.parse_yahoo_financials(payload, "A", "2013-12-31", start="2013-01-01")[0]["revenue"], 0)
        self.assertEqual(info.parse_yahoo_financials(payload, "A", "2026-11-18", start="2014-01-01"), [])
        naver = {"financeInfo": {"trTitleList": [{"key": "201312", "isConsensus": "N"}],
                                  "rowList": [{"title": "영업이익", "columns": {"201312": {"value": "-7"}}}]}}
        self.assertEqual(info.parse_naver_financials(naver, "annual", "2013-12-31", start="2013-01-01")[0]["operating_income"], -7e8)

    def test_parallel_requests_have_independent_provider_period_filters(self):
        def response(url):
            params = parse_qs(urlparse(url).query)
            year = datetime.fromtimestamp(int(params["period1"][0]), timezone.utc).year
            records = [{"asOfDate": f"{y}-12-31", "periodType": "12M", "currencyCode": "USD", "reportedValue": {"raw": 0}}
                       for y in [year - 1, year, year + 1]]
            return {"timeseries": {"result": [{"meta": {"symbol": ["AAPL"]}, "annualTotalRevenue": records}]}}
        requests = [financial_request(year=year) for year in [2014, 2023, 2015, 2024]]
        with patch.object(info, "fetch_json", side_effect=response), ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda request: recovery.fetch({"ticker": "AAPL", "market": "us"}, request), requests))
        for request, (rows, errors) in zip(requests, results):
            self.assertFalse(errors)
            self.assertEqual([row["period_end"] for row in rows], [request.end])

    def test_merge_preserves_later_periods_currencies_zero_and_input(self):
        request = financial_request(year=2014)
        previous = {"quote": {"price": 99.123456789}, "metrics": {"per": 20}, "requested_start": "2010-01-01",
                    "financials": [statement(2015), statement(2014, currency="KRW", revenue=5)]}
        original = copy.deepcopy(previous)
        result = recovery.merge(previous, [statement(2014), statement(2016, revenue=100)], "checked", request)
        self.assertEqual(previous, original)
        self.assertEqual(result["quote"], previous["quote"])
        self.assertEqual(result["metrics"], previous["metrics"])
        self.assertEqual(result["requested_start"], "2010-01-01")
        self.assertIn(statement(2015), result["financials"])
        self.assertIn(statement(2014), result["financials"])
        self.assertNotIn(statement(2016, revenue=100), result["financials"])
        self.assertEqual(result[request.coverage_key]["periods"], 2)

    def fixture(self, root, stack, tickers=("AAPL",)):
        for target, name, value in [(info, "ROOT", root), (info, "PACKS", root / "packs")]:
            stack.enter_context(patch.object(target, name, value))
        state = root / "state"
        db = info.open_database(state)
        for ticker in tickers:
            value = {"ticker": ticker, "quote": {"price": 99}, "metrics": {}, "financials": [statement(2025)]}
            db.execute("INSERT INTO information VALUES (?,?)", (ticker, json.dumps(value)))
        db.commit(); db.close()
        return state, [{"ticker": ticker, "order": index + 1, "market": "us"} for index, ticker in enumerate(tickers)]

    def test_years_share_database_without_sharing_completion_receipts(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            state, rows = self.fixture(root, stack)
            def fetch(row, scanner, request):
                return [statement(int(request.start[:4]))], [], None
            with patch.object(recovery, "fetch_with_current", side_effect=fetch) as fetcher, redirect_stdout(io.StringIO()):
                for year in [2014, 2015, 2014, 2015]:
                    request = replace(financial_request(year=year, root=root), state=state)
                    recovery.main(["collect"], request=request, rows=rows)
            self.assertEqual(fetcher.call_count, 2)
            db = info.open_database(state)
            value = json.loads(db.execute("SELECT value FROM information").fetchone()[0])
            self.assertEqual([s["period_end"] for s in value["financials"]], ["2014-12-31", "2015-12-31", "2025-12-31"])
            self.assertEqual(value["quote"], {"price": 99})
            for year in [2014, 2015]:
                self.assertEqual(db.execute(f"SELECT count(*) FROM financial_{year}_updates").fetchone()[0], 1)
                report = json.loads((root / f"data/information-audit/{year}/financial-progress.json").read_bytes())
                self.assertEqual(report["pending"], 0)
                self.assertEqual(report["requested_start"], f"{year}-01-01")
            db.close()

    def test_access_denied_checkpoints_completed_rows_and_resumes_pending_rows(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            state, rows = self.fixture(root, stack, ("AAPL", "MSFT"))
            request = replace(financial_request(year=2014, root=root), state=state)
            denied = HTTPError("fixture", 403, "denied", None, None)
            def fetch(row, scanner, request):
                if row["ticker"] == "MSFT":
                    raise denied
                return [statement(2014)], [], None
            with patch.object(recovery, "fetch_with_current", side_effect=fetch), redirect_stdout(io.StringIO()), self.assertRaises(HTTPError):
                recovery.main(["collect"], request=request, rows=rows)
            report = json.loads((request.audit / "financial-progress.json").read_bytes())
            self.assertEqual((report["checked"], report["next"]["ticker"]), (1, "MSFT"))
            with patch.object(recovery, "fetch_with_current", return_value=([statement(2014)], [], None)) as fetcher, redirect_stdout(io.StringIO()):
                recovery.main(["collect"], request=request, rows=rows)
            self.assertEqual(fetcher.call_args.args[0]["ticker"], "MSFT")
            self.assertEqual(fetcher.call_count, 1)

    def test_ongoing_range_rechecks_a_new_endpoint(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            state, rows = self.fixture(root, stack)
            request = replace(financial_request(root=root, as_of="2026-11-17"), state=state)
            with patch.object(recovery, "fetch_with_current", return_value=([], [], None)) as fetcher, redirect_stdout(io.StringIO()):
                recovery.main(["collect"], request=request, rows=rows)
                recovery.main(["collect"], request=request, rows=rows)
                recovery.main(["collect"], request=replace(request, end="2026-11-18"), rows=rows)
            self.assertEqual(fetcher.call_count, 2)

    def test_configuration_and_worker_errors_fail_before_database_access(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(info, "open_database", side_effect=AssertionError("No database")):
            path = Path(folder) / "invalid.json"
            path.write_text('{"invalid":true}', encoding="utf-8")
            for args in [["collect", "--history-config", str(path)], ["collect", "--workers", "99", "--dry-run"], ["collect", "--limit", "-1"]]:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    recovery.main(args)
                self.assertEqual(caught.exception.code, 2)

    def test_export_keeps_original_request_metadata_and_values(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(info, "PACKS", Path(folder)):
            db = sqlite3.connect(":memory:")
            db.execute("CREATE TABLE information(ticker TEXT PRIMARY KEY,value TEXT)")
            value = {"ticker": "A", "requested_start": "2015-01-01", "financials": [statement(2015)]}
            db.execute("INSERT INTO information VALUES ('A', ?)", (json.dumps(value),))
            with redirect_stdout(io.StringIO()):
                info.export(db)
            saved = {ticker: v for path in Path(folder).glob("*.gz") for ticker, v in json.loads(gzip.decompress(path.read_bytes())).items()}
            self.assertEqual(saved["A"], value)
            db.close()

    def test_generic_cli_keeps_exact_configuration_in_resume_command(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history config.json"
            value = json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))
            value["collection"].update(start_year=2013, end_year=2013)
            path.write_text(json.dumps(value), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output), patch.object(info, "open_database", side_effect=AssertionError("No database")):
                recovery.main(["collect", "--history-config", str(path), "--dry-run"])
            result = json.loads(output.getvalue())
            self.assertEqual(result["table"], "financial_2013_updates")
            self.assertIn('--history-config "', result["resume"])
            self.assertEqual(result["end"], "2013-12-31")


if __name__ == "__main__":
    unittest.main()
