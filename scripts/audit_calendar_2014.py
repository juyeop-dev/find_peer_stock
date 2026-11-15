"""Validate 2014 sessions and the actual historical sector cohort."""
import json
from stock_chart_history import ROOT, write_json
from audit_calendar_2023 import main as audit_calendars


def main():
    audit_calendars(year=2014, minimum_sector_matches=0, minimum_sector_match_ratio=.95)
    audit_replay()


def audit_replay():
    replay = json.loads((ROOT / 'data/chart-replay/markets.json').read_bytes())
    kospi = next(row for row in replay['markets'] if row['ticker'] == '^KS11')
    gold = next(row for row in replay['markets'] if row['ticker'] == 'GC=F')
    indices = json.loads((ROOT / 'data/investors/index.json').read_bytes())
    # The historical index archive is checked against actual dated source bars.
    expected = {row['date']: row for row in indices['history'] if row['date'].startswith('2014-')}
    observed = {row['date']: row for row in kospi['bars'] if row['date'].startswith('2014-')}
    assert len(expected) == 245 and set(observed) == set(expected)
    for day, row in observed.items():
        original = next(market['index'] for market in expected[day]['markets'] if market['market'] == 'KOSPI')
        for field in ['open', 'high', 'low', 'close']:
            assert row[field] == original[field], (day, field)
    gold_bars = [row for row in gold['bars'] if row['date'].startswith('2014-')]
    assert len(gold_bars) >= 240 and gold_bars[0]['date'] == '2014-01-02'
    assert all(0 < row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high'] for row in gold_bars)
    write_json(ROOT / 'data/information-audit/2014/replay-coverage.json', {'kospi_sessions': len(observed), 'gold_sessions': len(gold_bars), 'first_kospi': min(observed), 'first_gold': gold_bars[0]['date'], 'actual_observations_only': True})

if __name__ == "__main__":
    main()
