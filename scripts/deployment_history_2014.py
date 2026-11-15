"""Keep the whole verified incoming prefix and noncontradicted listing dates."""
import math
from datetime import date, timedelta


def trading_dates_2014(config):
    weekdays = {str(date(2014, 1, 1) + timedelta(days=i)) for i in range(365)
                if (date(2014, 1, 1) + timedelta(days=i)).weekday() < 5}
    return {row['market']: (weekdays | set(row.get('additional_open_dates', {}))) - set(row['dates'])
            for row in config['markets']}


def regular_session_curve(value, allowed):
    if allowed is None:
        return value
    bad = lambda prices: sorted(point[0] for point in prices if point[0].startswith('2014-') and point[0] not in allowed)
    excluded = bad(value['prices'])
    result = dict(value)
    snapshots = list(value.get('prior_snapshots', []))
    if excluded:
        snapshots.append({**{k: v for k, v in value.items() if k != 'prior_snapshots'},
                          'complete_history': False, 'preservation_reason': 'Unchanged provider original; officially closed 2014 sessions excluded from the regular chart'})
        result['prices'] = [point for point in value['prices'] if point[0] not in set(excluded)]
        result['excluded_2014_closed_dates'] = sorted(set(value.get('excluded_2014_closed_dates', [])) | set(excluded))
    validated = []
    for snapshot in snapshots:
        closed = bad(snapshot['prices'])
        if closed and snapshot.get('complete_history'):
            snapshot = {**snapshot, 'complete_history': False, 'excluded_2014_closed_dates': closed,
                        'release_2014_prior_validation': {'complete_history': snapshot.get('complete_history'),
                            'preservation_reason': snapshot.get('preservation_reason')}}
        validated.append(snapshot)
    if snapshots or 'prior_snapshots' in value:
        result['prior_snapshots'] = validated
    return result


def prefer_verified_2014_original(value):
    candidates = []
    for curve in [value, *value.get('prior_snapshots', [])]:
        extension = curve.get('historical_2014_extension', {})
        proof = extension.get('official_saturday_quotes', {}).get('2014-12-27')
        if not proof or curve.get('currency') != 'TWD' or proof['chart_sha256'] != extension.get('source_sha256'):
            continue
        close = proof['original_bar']['close'] * proof['factor']
        if ['2014-12-27', close, close] in curve['prices']:
            candidates.append(curve)
    if not candidates or value in candidates:
        return value
    chosen = max(candidates, key=lambda curve: curve['prices'][-1][0])
    result = {k: v for k, v in chosen.items() if k not in ['prior_snapshots', 'complete_history', 'preservation_reason']}
    result['prior_snapshots'] = [*value.get('prior_snapshots', []),
        {**{k: v for k, v in value.items() if k != 'prior_snapshots'}, 'complete_history': True,
         'preservation_reason': 'Latest source kept separately from the independently verified official Saturday price basis'}]
    return result


def join_release_prices(current, incoming):
    if len(current.get('prices', [])) < 2 or len(incoming.get('prices', [])) < 2:
        return None
    if current['ticker'] != incoming['ticker'] or current['currency'] != incoming['currency']:
        return None
    def union(primary, secondary):
        existing = {point[0]: point for point in primary['prices']}
        split_only = all(point[1] == point[2] for point in primary['prices'])
        candidates = [[day, close, close if split_only else adjusted] for day, close, adjusted in secondary['prices']]
        overlap = [(point, existing[point[0]]) for point in candidates if point[0] in existing]
        if len(overlap) < 3 or not all(math.isclose(a, b, rel_tol=1e-5, abs_tol=.005)
                                      for left, right in overlap for a, b in zip(left[1:], right[1:])):
            return None
        added = [point for point in candidates if point[0] not in existing]
        if not added:
            return dict(primary)
        observed = {point[0]: point for point in candidates}
        observed.update(existing)
        prices = [observed[day] for day in sorted(observed)]
        first = next((value for value in [primary.get('first_trade_date'), secondary.get('first_trade_date')]
                      if value and value <= prices[0][0]), None)
        result = {**primary, 'prices': prices, 'first_trade_date': first,
                  'release_2014_observation_merge': {'secondary_source': secondary.get('source'),
                      'verified_overlap': len(overlap), 'added_dates': [point[0] for point in added],
                      'price_convention': 'split-adjusted close' if split_only else 'observed close and adjusted close'}}
        if prices[-1][0] > primary['prices'][-1][0]:
            for key in ['fetched_at', 'provider_date']:
                if key in secondary:
                    result[key] = secondary[key]
        return result
    # Preserve genuine interior sessions too (notably the official Taiwan
    # Saturday). Reverse only to a separately verified split-only convention;
    # both original curves remain in the caller's preservation snapshots.
    return union(current, incoming) or union(incoming, current)


def retain_listing_date(primary, incoming):
    first = incoming.get('first_trade_date')
    prices = primary.get('prices', [])
    if not primary.get('first_trade_date') and first and prices and first <= prices[0][0]:
        return {**primary, 'first_trade_date': first}
    return primary
