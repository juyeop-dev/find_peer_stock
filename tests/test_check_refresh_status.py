from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_refresh_status as refresh_check  # noqa: E402


class CheckRefreshStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 12, 6, 30, tzinfo=timezone.utc)

    def test_offset_timestamp_and_utc_timestamp_have_the_same_age(self) -> None:
        for value in ("2026-09-12T15:15:00+09:00", "2026-09-12T06:15:00Z"):
            with self.subTest(value=value):
                result = refresh_check.evaluate_refresh_status({"generated_at": value}, now=self.now)
                self.assertEqual(result["age_minutes"], 15)
                self.assertFalse(result["stale"])
                self.assertEqual(result["status"], "fresh")

    def test_age_limit_is_inclusive_and_over_limit_is_stale(self) -> None:
        for age, expected in ((0, False), (20 * 60, False), (20 * 60 + 1, True)):
            with self.subTest(age=age):
                generated_at = self.now - timedelta(seconds=age)
                result = refresh_check.evaluate_refresh_status(
                    {"generated_at": generated_at.isoformat()}, now=self.now
                )
                self.assertEqual(result["stale"], expected)

    def test_custom_age_limit(self) -> None:
        result = refresh_check.evaluate_refresh_status(
            {"generated_at": "2026-09-12T06:15:00Z"}, now=self.now, max_age_minutes=10
        )
        self.assertTrue(result["stale"])

    def test_missing_malformed_naive_and_future_timestamps_are_errors(self) -> None:
        invalid = [None, [], {}, {"generated_at": None}, {"generated_at": 123},
                   {"generated_at": ""}, {"generated_at": "invalid"},
                   {"generated_at": "2026-09-12T06:00:00"},
                   {"generated_at": "2026-09-12T06:30:00.000001Z"}]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                refresh_check.evaluate_refresh_status(payload, now=self.now)

    def test_invalid_limit_and_naive_current_time_are_errors(self) -> None:
        payload = {"generated_at": self.now.isoformat()}
        for limit in (0, -1, float("inf"), float("nan")):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                refresh_check.evaluate_refresh_status(payload, now=self.now, max_age_minutes=limit)
        with self.assertRaisesRegex(ValueError, "now must include a timezone"):
            refresh_check.evaluate_refresh_status(payload, now=self.now.replace(tzinfo=None))

    def test_cli_exit_codes_for_fresh_stale_and_fetch_errors(self) -> None:
        for age, expected_code in ((5, 0), (25, 1)):
            payload = {"generated_at": (datetime.now(timezone.utc) - timedelta(minutes=age)).isoformat()}
            output = io.StringIO()
            with self.subTest(age=age), patch.object(refresh_check, "fetch_site_index", return_value=payload), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(refresh_check.main([]), expected_code)
            self.assertEqual(json.loads(output.getvalue())["stale"], bool(expected_code))
        for error in (urllib.error.URLError("offline"), json.JSONDecodeError("invalid JSON", "", 0)):
            output = io.StringIO()
            with self.subTest(error=error), patch.object(refresh_check, "fetch_site_index", side_effect=error), \
                 contextlib.redirect_stderr(output):
                self.assertEqual(refresh_check.main([]), 1)
            self.assertEqual(json.loads(output.getvalue())["status"], "error")

    def test_fetch_uses_cache_bypass_for_base_and_full_index_urls(self) -> None:
        for site_url in ("https://example.com/site/", "https://example.com/site/data/index.json"):
            response = io.BytesIO(b'{"generated_at": "2026-09-12T06:30:00Z"}')
            with self.subTest(site_url=site_url), \
                 patch.object(refresh_check.urllib.request, "urlopen", return_value=response) as fetch:
                payload = refresh_check.fetch_site_index(site_url)
                request = fetch.call_args.args[0]
                self.assertTrue(request.full_url.startswith("https://example.com/site/data/index.json?_refresh_check="))
                self.assertEqual(request.get_header("Cache-control"), "no-cache, no-store")
                self.assertEqual(fetch.call_args.kwargs["timeout"], 20)
                self.assertIn("generated_at", payload)


if __name__ == "__main__":
    unittest.main()
