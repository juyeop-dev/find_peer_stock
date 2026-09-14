from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import refresh_new_highs as refresh
import generate_new_high_data as generator


class DailyRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source"
        self.source.mkdir()
        self.market = {"id": "korea", "label": "한국", "timezone": "Asia/Seoul", "default_exchange": "KOSPI",
                       "exchanges": [{"id": "KOSPI", "label": "코스피"}]}
        (self.source / "markets.json").write_text(json.dumps({"schema_version": 1, "markets": [self.market]}), encoding="utf-8")
        self.report = {"schema_version": 1, "market": "korea", "date": "2026-09-11", "entries": []}
        self.now = datetime.fromisoformat("2026-09-11T16:30:00+09:00")

    def collect(self, fetch, now=None):
        return refresh.refresh_new_highs(self.source, now=now or self.now, fetch_report=fetch)

    def test_after_close_boundary_weekend_catchup_and_market_open(self):
        for stamp, expected in [
            ("2026-09-11T16:29:59+09:00", None),
            ("2026-09-11T16:30:00+09:00", date(2026, 9, 11)),
            ("2026-09-13T12:00:00+09:00", date(2026, 9, 11)),
            ("2026-09-14T08:29:59+09:00", date(2026, 9, 11)),
            ("2026-09-14T08:30:00+09:00", None),
        ]:
            with self.subTest(stamp=stamp):
                self.assertEqual(refresh.collection_date(self.market, datetime.fromisoformat(stamp)), expected)

    def test_us_daylight_saving_and_local_trading_date(self):
        market = {"id": "us", "timezone": "America/New_York"}
        cases = [("2026-07-07T20:59:00+00:00", None), ("2026-07-07T21:00:00+00:00", date(2026, 7, 7)),
                 ("2026-01-07T21:59:00+00:00", None), ("2026-01-07T22:00:00+00:00", date(2026, 1, 7))]
        for stamp, expected in cases:
            self.assertEqual(refresh.collection_date(market, datetime.fromisoformat(stamp)), expected)

    def test_success_is_fetched_once_across_repeated_process_runs(self):
        fetch = Mock(return_value=self.report)
        first = self.collect(fetch)
        path = self.source / "reports/korea/2026-09-11.json"
        original = path.read_bytes()
        self.collect(fetch, self.now + timedelta(minutes=5))
        self.collect(fetch, self.now + timedelta(days=2))
        fetch.assert_called_once_with("korea", date(2026, 9, 11))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(first["markets"]["korea"]["last_success_date"], "2026-09-11")

    def test_failure_retries_after_thirty_minutes_without_empty_report(self):
        fetch = Mock(side_effect=[OSError("temporary failure"), self.report])
        state = self.collect(fetch)
        self.assertEqual(state["markets"]["korea"]["status"], "error")
        self.assertFalse((self.source / "reports/korea/2026-09-11.json").exists())
        self.collect(fetch, self.now + timedelta(minutes=29))
        self.assertEqual(fetch.call_count, 1)
        recovered = self.collect(fetch, self.now + timedelta(minutes=30))
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(recovered["markets"]["korea"]["status"], "updated")
        self.assertNotIn("next_retry_at", recovered["markets"]["korea"])

    def test_stale_holiday_data_stays_pending_and_is_not_saved(self):
        from new_high_sources.tradingview import TradingViewSourceNotReady
        refresh.atomic_json(self.source / "refresh-status.json", {
            "schema_version": 1,
            "markets": {"korea": {
                "status": "error", "target_date": "2026-09-10",
                "last_attempt_at": "2026-09-10T16:30:00+09:00",
                "last_success_at": "2026-09-09T16:30:00+09:00",
                "last_success_date": "2026-09-09",
                "next_retry_at": "2026-09-10T17:00:00+09:00",
                "message": "old", "obsolete": "must disappear",
            }},
        })
        state = self.collect(Mock(side_effect=TradingViewSourceNotReady("No current session")))
        self.assertEqual(state["markets"]["korea"], {
            "status": "pending",
            "target_date": "2026-09-11",
            "last_attempt_at": self.now.isoformat(),
            "last_success_at": "2026-09-09T16:30:00+09:00",
            "last_success_date": "2026-09-09",
            "next_retry_at": (self.now + timedelta(minutes=30)).isoformat(),
            "message": "해당 거래일 자료 확인 대기 중입니다.",
        })
        self.assertFalse((self.source / "reports/korea/2026-09-11.json").exists())

    def test_retry_wait_is_canonicalized_without_fetching(self):
        refresh.atomic_json(self.source / "refresh-status.json", {
            "schema_version": 1,
            "markets": {"korea": {
                "status": "error", "target_date": "2026-09-11",
                "last_attempt_at": self.now.isoformat(),
                "last_success_at": "2026-09-10T16:30:00+09:00",
                "last_success_date": "2026-09-10",
                "next_retry_at": (self.now + timedelta(minutes=30)).isoformat(),
                "message": "old", "obsolete": "must disappear",
            }},
        })

        fetch = Mock()
        state = self.collect(fetch, self.now + timedelta(minutes=5))

        fetch.assert_not_called()
        self.assertEqual(state["markets"]["korea"], {
            "status": "error",
            "target_date": "2026-09-11",
            "last_attempt_at": self.now.isoformat(),
            "last_success_at": "2026-09-10T16:30:00+09:00",
            "last_success_date": "2026-09-10",
            "next_retry_at": (self.now + timedelta(minutes=30)).isoformat(),
            "message": "수집 또는 검증에 실패해 기존 기록을 보존했습니다.",
        })

    def test_wrong_date_and_invalid_entries_are_rejected(self):
        for report in [{**self.report, "date": "2026-09-10"}, {**self.report, "entries": [{}]},
                       {**self.report, "schema_version": True}]:
            with self.subTest(report=report):
                state = self.collect(Mock(return_value=report), self.now)
                self.assertEqual(state["markets"]["korea"]["status"], "error")
                self.assertFalse((self.source / "reports/korea/2026-09-11.json").exists())
                (self.source / "refresh-status.json").unlink()

    def test_registered_curated_report_is_never_overwritten(self):
        path = self.source / "reports/korea/2026-09-11.json"
        refresh.atomic_json(path, self.report)
        original = path.read_bytes()
        fetch = Mock()
        self.collect(fetch)
        fetch.assert_not_called()
        self.assertEqual(path.read_bytes(), original)

    def test_curated_report_without_collection_time_clears_old_attempt_state(self):
        refresh.atomic_json(self.source / "refresh-status.json", {
            "schema_version": 1,
            "markets": {"korea": {
                "status": "error", "target_date": "2026-09-10",
                "last_attempt_at": "2026-09-10T16:30:00+09:00",
                "last_success_at": "2026-09-09T16:30:00+09:00",
                "last_success_date": "2026-09-09",
                "next_retry_at": "2026-09-10T17:00:00+09:00",
                "message": "old", "obsolete": "must disappear",
            }},
        })
        refresh.atomic_json(self.source / "reports/korea/2026-09-11.json", self.report)

        fetch = Mock()
        state = self.collect(fetch)

        fetch.assert_not_called()
        self.assertEqual(state["markets"]["korea"], {
            "status": "updated",
            "target_date": "2026-09-11",
            "last_success_date": "2026-09-11",
            "message": "이 거래일의 신고가 자료가 등록되었습니다.",
        })

    def test_unsupported_transition_removes_all_previous_market_state(self):
        refresh.atomic_json(self.source / "refresh-status.json", {
            "schema_version": 1,
            "markets": {"korea": {
                "status": "error", "target_date": "2026-09-11",
                "last_attempt_at": "2026-09-11T16:30:00+09:00",
                "last_success_at": "2026-09-10T16:30:00+09:00",
                "last_success_date": "2026-09-10",
                "next_retry_at": "2026-09-11T17:00:00+09:00",
                "message": "old", "obsolete": "must disappear",
            }},
        })
        from new_high_sources import tradingview

        fetch = Mock()
        with patch.object(tradingview, "SUPPORTED_MARKETS", frozenset()):
            state = self.collect(fetch)

        fetch.assert_not_called()
        self.assertEqual(state["markets"]["korea"], {
            "status": "unsupported",
            "message": "자동 수집을 지원하는 자료원을 준비 중입니다.",
        })

    def test_open_session_clears_retry_state_but_keeps_success_history(self):
        refresh.atomic_json(self.source / "refresh-status.json", {
            "schema_version": 1,
            "markets": {"korea": {
                "status": "error", "target_date": "2026-09-10",
                "last_attempt_at": "2026-09-10T16:30:00+09:00",
                "last_success_at": "2026-09-09T16:30:00+09:00",
                "last_success_date": "2026-09-09",
                "next_retry_at": "2026-09-10T17:00:00+09:00",
                "message": "old", "obsolete": "must disappear",
            }},
        })

        fetch = Mock()
        state = self.collect(fetch, self.now - timedelta(hours=1))

        fetch.assert_not_called()
        self.assertEqual(state["markets"]["korea"], {
            "status": "pending",
            "target_date": "2026-09-11",
            "last_success_at": "2026-09-09T16:30:00+09:00",
            "last_success_date": "2026-09-09",
            "message": "장 마감 후 일별 자료를 확인합니다.",
        })

    def test_error_replaces_stale_retry_state_and_preserves_only_success_history(self):
        refresh.atomic_json(self.source / "refresh-status.json", {
            "schema_version": 1,
            "markets": {"korea": {
                "status": "pending", "target_date": "2026-09-10",
                "last_attempt_at": "2026-09-10T16:30:00+09:00",
                "last_success_at": "2026-09-09T16:30:00+09:00",
                "last_success_date": "2026-09-09",
                "next_retry_at": "2026-09-10T17:00:00+09:00",
                "message": "old", "obsolete": "must disappear",
            }},
        })

        state = self.collect(Mock(side_effect=OSError("temporary failure")))

        self.assertEqual(state["markets"]["korea"], {
            "status": "error",
            "target_date": "2026-09-11",
            "last_attempt_at": self.now.isoformat(),
            "last_success_at": "2026-09-09T16:30:00+09:00",
            "last_success_date": "2026-09-09",
            "next_retry_at": (self.now + timedelta(minutes=30)).isoformat(),
            "message": "수집 또는 검증에 실패해 기존 기록을 보존했습니다.",
        })

    def test_each_early_branch_is_saved_before_a_later_market_exception(self):
        japan = {"id": "japan", "label": "일본", "timezone": "Asia/Tokyo", "default_exchange": "TSE",
                 "exchanges": [{"id": "TSE", "label": "도쿄"}]}
        from new_high_sources import tradingview

        scenarios = [
            ("unsupported", frozenset({"japan"}), [RuntimeError("later market")], None, None),
            ("open", tradingview.SUPPORTED_MARKETS, [None, RuntimeError("later market")], None, None),
            ("existing", tradingview.SUPPORTED_MARKETS,
             [date(2026, 9, 11), RuntimeError("later market")], self.report, None),
            ("retry_wait", tradingview.SUPPORTED_MARKETS,
             [date(2026, 9, 11), RuntimeError("later market")], None, {
                 "status": "error", "target_date": "2026-09-11",
                 "last_attempt_at": self.now.isoformat(),
                 "next_retry_at": (self.now + timedelta(minutes=30)).isoformat(),
                 "message": "old",
             }),
        ]
        for name, supported, dates, report, previous in scenarios:
            with self.subTest(branch=name), tempfile.TemporaryDirectory() as directory:
                source = Path(directory)
                (source / "markets.json").write_text(json.dumps({
                    "schema_version": 1, "markets": [self.market, japan],
                }), encoding="utf-8")
                if report is not None:
                    refresh.atomic_json(source / "reports/korea/2026-09-11.json", report)
                if previous is not None:
                    refresh.atomic_json(source / "refresh-status.json", {
                        "schema_version": 1, "markets": {"korea": previous},
                    })

                with patch.object(tradingview, "SUPPORTED_MARKETS", supported), \
                     patch.object(refresh, "collection_date", side_effect=dates), \
                     self.assertRaisesRegex(RuntimeError, "later market"):
                    refresh.refresh_new_highs(source, now=self.now, fetch_report=Mock())

                persisted = json.loads((source / "refresh-status.json").read_text(encoding="utf-8"))
                self.assertEqual(persisted["markets"]["korea"]["status"], name if name == "unsupported" else {
                    "open": "pending", "existing": "updated", "retry_wait": "error",
                }[name])
                self.assertNotIn("japan", persisted["markets"])

    def test_open_session_does_not_fetch_and_status_reaches_both_outputs(self):
        fetch = Mock()
        self.collect(fetch, self.now - timedelta(hours=1))
        fetch.assert_not_called()
        output = Path(self.temp.name) / "generated"
        frontend = Path(self.temp.name) / "frontend"
        index = generator.generate_new_high_data(self.source, output, frontend)
        self.assertEqual(index["refresh"]["korea"]["status"], "pending")
        self.assertEqual(index["reports"], [])
        self.assertEqual((output / "new-highs/index.json").read_bytes(), (frontend / "new-highs/index.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
