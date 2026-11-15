from datetime import date, datetime, timezone
import hashlib
import gzip
import json
import sqlite3
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from backfill_yahoo_calendars import requested_dates
import refresh_stock_information_history as refresh
import finalize_2014 as coordinator
import import_taiwan_official_histories_2014 as taiwan_import
from audit_taiwan_quality_2014 import verify_original_curves
import audit_stock_information_2024_h2 as information_audit
from deployment_history_2014 import join_release_prices, retain_listing_date, regular_session_curve, prefer_verified_2014_original
from semiconductor_provenance import archive_semiconductor, hydrate_semiconductor, REFERENCE
import generate_semiconductor_data as semiconductor


class Historical2014Tests(unittest.TestCase):
    def test_officially_verified_saturday_basis_is_promoted_with_the_latest_original_retained(self):
        latest = {'ticker': 'TEST', 'currency': 'TWD', 'source': 'latest', 'prices': [['2014-12-26', 10, 9], ['2026-11-13', 20, 19]]}
        proof = {'chart_sha256': 'verified-source', 'original_bar': {'close': 100}, 'factor': .1}
        verified = {'ticker': 'TEST', 'currency': 'TWD', 'source': 'verified original',
                    'prices': [['2014-12-26', 10, 10], ['2014-12-27', 10, 10], ['2026-11-04', 20, 20]],
                    'historical_2014_extension': {'source_sha256': 'verified-source', 'official_saturday_quotes': {'2014-12-27': proof}}}
        original = {**latest, 'prior_snapshots': [verified]}
        chosen = prefer_verified_2014_original(original)
        self.assertEqual(chosen['prices'], verified['prices'])
        self.assertEqual(chosen['prior_snapshots'][-1]['prices'], latest['prices'])
        self.assertEqual(prefer_verified_2014_original({**latest, 'prior_snapshots': [{**verified, 'historical_2014_extension': {}}]}), {**latest, 'prior_snapshots': [{**verified, 'historical_2014_extension': {}}]})

    def test_closed_provider_values_stay_as_originals_while_verified_saturday_remains_regular(self):
        value = {'ticker': 'TEST', 'currency': 'TWD', 'source': 'original',
                 'prices': [['2014-07-23', 10, 10], ['2014-12-27', 20, 20]],
                 'prior_snapshots': [{'ticker': 'TEST', 'currency': 'TWD', 'source': 'prior',
                                      'complete_history': True, 'prices': [['2014-07-23', 9, 9]]}]}
        result = regular_session_curve(value, {'2014-12-27'})
        self.assertEqual(result['prices'], [['2014-12-27', 20, 20]])
        self.assertEqual(result['prior_snapshots'][-1]['prices'], value['prices'])
        self.assertFalse(result['prior_snapshots'][0]['complete_history'])
        self.assertTrue(result['prior_snapshots'][0]['release_2014_prior_validation']['complete_history'])
        self.assertTrue(value['prior_snapshots'][0]['complete_history'])

    def test_verified_interior_session_survives_identical_starts_and_dividend_conventions_stay_separate(self):
        prices = [['2014-12-26', 10, 10], ['2014-12-29', 11, 11], ['2014-12-30', 12, 12]]
        current = {'ticker': 'TEST', 'currency': 'TWD', 'source': 'current', 'prices': prices}
        original = {**current, 'source': 'official recovered curve', 'prices': [prices[0], ['2014-12-27', 10.5, 10.5], *prices[1:]]}
        self.assertEqual(join_release_prices(current, original)['prices'], original['prices'])
        dividend = {**current, 'prices': [[day, close, close-1] for day, close, _ in prices]}
        merged = join_release_prices(dividend, original)
        self.assertEqual(merged['prices'], original['prices'])
        self.assertEqual(merged['source'], original['source'])
        self.assertIsNone(join_release_prices(current, {**original, 'currency': 'USD'}))
        self.assertIsNone(join_release_prices(current, {**original, 'prices': [[day, close*2, adjusted*2] for day, close, adjusted in original['prices']]}))

    def test_private_semiconductor_archives_restore_duplicates_metadata_and_identical_public_output(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'semiconductor'
            directory.mkdir()
            source = directory / 'index.json'
            history = [{'date': '2014-01-02', 'close': 10.123456789012345, 'adjusted_close': 9.87654321098765, 'volume': None}]
            snapshot = {'history': history, 'source': '원본', 'source_generated_at': '2015-01-02'}
            original = {'schema_version': 1, 'stocks': [{'ticker': '000660.KS', 'code': '000660', 'name': '종목',
                'history': history, 'quarterly_financials': [], 'annual_financials': [],
                'prior_history_snapshots': [snapshot, {**snapshot, 'reason': 'metadata differs'}, snapshot]}]}
            source.write_text(json.dumps(original), encoding='utf-8')
            quote = {'market': 'KOSPI', 'name': '종목', 'price': 10, 'provider_time': '2014-01-02'}
            now = datetime(2026, 11, 15, tzinfo=timezone.utc)
            with patch.object(semiconductor, 'fetch_current_quote', return_value=quote):
                public_before = semiconductor.publish(source, directory / 'public.json', now=now)
                semiconductor.write_json(source, original)
                packed = json.loads(source.read_bytes())
                self.assertNotIn('prior_history_snapshots', packed['stocks'][0])
                self.assertEqual(hydrate_semiconductor(packed, directory), original)
                self.assertEqual(semiconductor.load_existing(source), original)
                self.assertEqual(archive_semiconductor(packed, directory), packed)
                self.assertEqual(len(list((directory / 'preserved-snapshots').glob('*.json.gz'))), 1)
                public_after = semiconductor.publish(source, directory / 'public.json', now=now)
            self.assertEqual(public_before, public_after)
            self.assertNotIn(REFERENCE, public_after['stocks'][0])

    def test_semiconductor_archive_corruption_and_wrong_paths_propagate_as_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'semiconductor'
            source = directory / 'index.json'
            original = {'stocks': [{'ticker': 'TEST', 'history': [], 'prior_history_snapshots': [{'history': [], 'source': 'original'}]}]}
            semiconductor.write_json(source, original)
            packed = json.loads(source.read_bytes())
            reference = packed['stocks'][0][REFERENCE]
            archive = directory / reference['file']
            archive.write_bytes(archive.read_bytes() + b'changed')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                semiconductor.load_existing(source)
            reference['file'] = '../outside.json.gz'
            with self.assertRaisesRegex(ValueError, 'designated source directory'):
                hydrate_semiconductor(packed, directory)

    def test_release_preserves_distant_observed_prefix_and_only_noncontradicted_listing_dates(self):
        current = {'ticker': 'TEST', 'currency': 'EUR', 'prices': [
            ['2015-01-02', 20, 20], ['2015-01-05', 21, 21], ['2015-01-06', 22, 22], ['2026-11-13', 30, 30]]}
        incoming = {**current, 'prices': [['2000-01-04', 10, 10], ['2014-11-03', 19, 19], *current['prices']]}
        merged = join_release_prices(current, incoming)
        self.assertEqual(merged['prices'], incoming['prices'])
        later = {'ticker': 'IPO', 'currency': 'GBP', 'prices': [['2021-01-28', 10, 10], ['2026-11-13', 20, 20]]}
        self.assertEqual(retain_listing_date(later, {'first_trade_date': '2021-01-28'})['first_trade_date'], '2021-01-28')
        self.assertNotIn('first_trade_date', retain_listing_date(later, {'first_trade_date': '2022-01-01'}))
        self.assertEqual(retain_listing_date({**later, 'first_trade_date': '2020-01-01'}, {'first_trade_date': '2021-01-28'})['first_trade_date'], '2020-01-01')

    def test_sharded_audit_preserves_roster_order_coverage_and_invalid_price_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            info, history = root / 'info', root / 'history'
            info.mkdir(); history.mkdir()
            rows = [{'ticker': ticker, 'market': 'us', 'order': index} for index, ticker in enumerate(['AAPL', 'MSFT', 'NVDA', 'TEST'])]
            curves = {
                'AAPL': {'prices': [['2024-06-28', 10, 10], ['2024-12-31', 11, 11]]},
                'MSFT': {'prices': [['2024-08-01', 10, 10], ['2024-12-31', 11, 11]], 'first_trade_date': '2024-08-01'},
                'NVDA': {'prices': [['2024-09-01', 10, 10], ['2024-12-31', 11, 11]]},
                'TEST': {'prices': []},
            }
            def store():
                for shard in '0123456789abcdef':
                    tickers = [row['ticker'] for row in rows if hashlib.sha256(row['ticker'].encode()).hexdigest()[0] == shard]
                    (info / f'{shard}.json.gz').write_bytes(gzip.compress(json.dumps({ticker: {'ticker': ticker, 'financials': []} for ticker in tickers}).encode()))
                    (history / f'{shard}.json.gz').write_bytes(gzip.compress(json.dumps({ticker: {'ticker': ticker, 'currency': 'USD', 'source': 'Original', **curves[ticker]} for ticker in tickers}).encode()))
            store()
            with patch.object(information_audit.information, 'PACKS', info), \
                 patch.object(information_audit.information, 'AUDIT', root / 'audit'), \
                 patch.object(information_audit.charts, 'PACKS', history), \
                 patch.object(information_audit.charts, 'roster', return_value=rows):
                information_audit.main()
                output = json.loads((root / 'audit/2024-h2/coverage-results.json').read_bytes())
                self.assertEqual([row['ticker'] for row in output], [row['ticker'] for row in rows])
                self.assertEqual([row['history_status'] for row in output], ['covers_h2_2024', 'later_listing', 'source_limited', 'missing_history'])
                curves['AAPL']['prices'][0][1] = -1
                store()
                with self.assertRaises(AssertionError):
                    information_audit.main()

    def test_closed_provider_point_requires_unchanged_original_and_open_days_cannot_disappear(self):
        expected = {day: [day, 10, 10] for day in ['2014-07-22', '2014-07-23', '2014-07-24']}
        original = {'currency': 'TWD', 'prices': list(expected.values()),
                    'historical_2014_extension': {'source_sha256': 'original', 'official_saturday_quotes': {}}}
        regular = {**original, 'prices': [expected['2014-07-22'], expected['2014-07-24']],
                   'excluded_2014_closed_dates': ['2014-07-23']}
        verify_original_curves([regular, original], expected, {'2014-07-23'}, 'TEST')
        with self.assertRaises(AssertionError):
            verify_original_curves([regular], expected, {'2014-07-23'}, 'TEST')
        with self.assertRaises(AssertionError):
            verify_original_curves([{**regular, 'prices': [expected['2014-07-22']]} , original], expected, {'2014-07-23'}, 'TEST')
        with self.assertRaises(AssertionError):
            verify_original_curves([regular, {**original, 'prices': [['2014-07-22', 10, 10], ['2014-07-23', 11, 11], ['2014-07-24', 10, 10]]}], expected, {'2014-07-23'}, 'TEST')

    def test_failed_sequential_stage_resumes_exact_failure_and_records_evidence(self):
        commands = [['python', 'first.py'], ['python', 'second.py'], ['python', 'third.py']]
        with tempfile.TemporaryDirectory() as folder, patch.object(coordinator, 'STATE', Path(folder)), \
             patch.object(coordinator.subprocess, 'run') as run:
            run.side_effect = [None, subprocess.CalledProcessError(1, commands[1])]
            with self.assertRaises(subprocess.CalledProcessError):
                coordinator.run('example', commands)
            self.assertEqual([call.args[0] for call in run.call_args_list], commands[:2])
            run.reset_mock()
            run.side_effect = None
            with patch.object(coordinator, 'RESUME_FAILED_COMMAND', True):
                coordinator.run('example', commands)
            self.assertEqual([call.args[0] for call in run.call_args_list], commands[1:])
            receipt = json.loads((Path(folder) / 'stage-example.json').read_bytes())
            self.assertEqual(receipt['status'], 'complete')
            self.assertEqual(receipt['completed_commands'], commands)
            self.assertEqual(receipt['previous_attempt']['status'], 'failed')

    def test_verified_taiwan_member_without_existing_detail_curve_is_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            symbol = 'TWSE:6197'
            ticker = '6197.TW'
            raw = json.dumps({'fetched_at': '2026-11-13T00:00:00Z'}).encode()
            cache = root / 'data/tmp_tradingview_chart/1D' / (hashlib.sha256(f'{symbol}:1D:3700'.encode()).hexdigest()+'.json')
            cache.parent.mkdir(parents=True)
            cache.write_bytes(raw)
            universe = root / 'data/tmp_2014/taiwan-gap-universe.json'
            universe.parent.mkdir(parents=True)
            universe.write_text(json.dumps({'rows': [{'symbol': symbol, 'name': '6197', 'exchange': 'TWSE'}]}))
            proof = root / 'data/information-audit/2014/taiwan-official-recovery-2014-12-27.json'
            proof.parent.mkdir(parents=True)
            proof.write_text(json.dumps({'date': '2014-12-27', 'members': {symbol: {
                'chart_sha256': hashlib.sha256(raw).hexdigest(), 'original_bar': {'close': 50}, 'factor': .5}}}))
            db = sqlite3.connect(':memory:')
            db.execute('CREATE TABLE history(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)')
            captured = {}
            def export(connection):
                captured['curve'] = json.loads(connection.execute('SELECT value FROM history WHERE ticker=?', (ticker,)).fetchone()[0])
            with patch.object(taiwan_import.charts, 'ROOT', root), \
                 patch.object(taiwan_import.charts, 'DATABASE', root / 'history.sqlite'), \
                 patch.object(taiwan_import.charts, 'database', return_value=db), \
                 patch.object(taiwan_import.charts, 'parse_tradingview', return_value={
                     'ticker': symbol, 'currency': 'TWD', 'source': 'TradingView',
                     'prices': [['2014-12-26', 24, 24], ['2014-12-29', 26, 26]]}), \
                 patch.object(taiwan_import.charts, 'export_packs', side_effect=export), \
                 patch('repair_taiwan_adjacent_2014.main'), patch('audit_taiwan_quality_2014.main'):
                taiwan_import.main()
            self.assertEqual(captured['curve']['ticker'], ticker)
            self.assertEqual(captured['curve']['prices'], [
                ['2014-12-26', 24, 24], ['2014-12-27', 25, 25], ['2014-12-29', 26, 26]])
            result = json.loads((proof.parent / 'taiwan-official-price-curves.json').read_bytes())
            self.assertEqual(result['added_verified_listings'], [ticker])

    def test_actual_2014_sessions_include_taiwan_saturday_and_exclude_typhoon(self):
        counts = {'korea': 245, 'us': 252, 'japan': 244, 'china': 245, 'taiwan': 248, 'europe': 256}
        for market, expected in counts.items():
            self.assertEqual(len(requested_dates(date(2014, 1, 1), date(2014, 12, 31), market)), expected)
        days = requested_dates(date(2014, 1, 1), date(2014, 12, 31), 'taiwan')
        self.assertIn(date(2014, 12, 27), days)
        self.assertNotIn(date(2014, 7, 23), days)

    def test_deep_daily_cache_is_used_without_refetching_a_confirmed_later_ipo(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / 'state'
            now = datetime.now(timezone.utc).isoformat()
            old = {'ticker': 'TEST', 'currency': 'USD', 'source': 'Yahoo', 'fetched_at': now,
                   'first_trade_date': '2015-01-02', 'prices': [['2015-01-02', 10, 10], ['2026-11-13', 20, 20]]}
            payload = {'symbol': 'NASDAQ:TEST', 'fetched_at': now, 'requested_bars': 3700,
                'info': {'pro_name': 'NASDAQ:TEST', 'source_id': 'NASDAQ', 'type': 'stock',
                         'currency_code': 'USD', 'timezone': 'America/New_York'},
                'bars': [{'timestamp': int(datetime.fromisoformat(day+'T20:00:00+00:00').timestamp()), 'close': close}
                         for day, close, _ in old['prices']]}
            cache = root / 'data/tmp_tradingview_chart/1D' / (hashlib.sha256(b'NASDAQ:TEST:1D:3700').hexdigest()+'.json')
            cache.parent.mkdir(parents=True)
            cache.write_text(json.dumps(payload), encoding='utf-8')
            row = {'ticker': 'TEST', 'exchange': 'NASDAQ', 'market': 'us', 'order': 1}
            with patch.object(refresh.information, 'ROOT', root), patch.object(refresh.information, 'START', '2014-01-01'), \
                 patch.object(refresh.information, 'PACKS', root / 'info-packs'), \
                 patch.object(refresh.charts, 'DATABASE', state / 'history.sqlite'), \
                 patch.object(refresh.charts, 'PACKS', root / 'history-packs'), \
                 patch.object(refresh.charts, 'roster', return_value=[row]), \
                 patch.object(refresh.information, 'checkpoint'), \
                 patch.object(refresh.information, 'fetch_json', side_effect=AssertionError('Cached listing should not be refetched')), \
                 patch.object(refresh, 'fallback', side_effect=AssertionError('Cached listing should not use fallback')), \
                 patch.object(sys, 'argv', ['refresh', '--state-dir', str(state), '--import-chart-cache', '--extend-to-start']):
                db = refresh.charts.database()
                db.execute('INSERT INTO history VALUES (?,?)', ('TEST', json.dumps(old)))
                db.commit()
                db.close()
                refresh.main()
                db = refresh.charts.database()
                value = json.loads(db.execute("SELECT value FROM history WHERE ticker='TEST'").fetchone()[0])
                db.close()
            self.assertEqual(value['first_trade_date'], '2015-01-02')
            self.assertEqual(value['prices'], old['prices'])


if __name__ == '__main__':
    unittest.main()
