"""Compare all published 2014 reports and domestic references to durable sources."""
import argparse
from datetime import date, timedelta
import gzip
import json
from pathlib import Path
from urllib.parse import quote

from stock_chart_history import ROOT, write_json
from deployment_history_2014 import trading_dates_2014


from publication_readers import load, load_published_sector_day, load_sector_listing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    public = (args.artifact.resolve() / "data") if args.artifact else ROOT / "frontend/public/data"
    counts = {}
    config = load(ROOT / "data/market-closures/2014.json")
    allowed = trading_dates_2014(config)
    source_calendar = load(ROOT / 'data/information-audit/2014/source-price-calendar.json.gz')['listings']
    markets = {row['ticker']: row['market'] for row in load(ROOT / 'data/information-audit/2014/coverage-results.json')}
    saturday = load(ROOT / 'data/information-audit/2014/taiwan-official-recovery-2014-12-27.json')['members']
    saturday_prices = {}
    for symbol, proof in saturday.items():
        exchange, code = symbol.split(':', 1)
        close = proof['original_bar']['close'] * proof['factor']
        saturday_prices[code + ('.TW' if exchange == 'TWSE' else '.TWO')] = ['2014-12-27', close, close]
    verified_source_calendars, verified_saturdays = set(), set()
    weekdays = {(date(2014, 1, 1) + timedelta(days=i)).isoformat() for i in range(365)
                if (date(2014, 1, 1) + timedelta(days=i)).weekday() < 5}
    expected = sum(len((weekdays | set(row.get("additional_open_dates", {}))) - set(row["dates"])) for row in config["markets"])
    for kind in ["new-highs", "turnover"]:
        count = 0
        for path in (ROOT / "data/generated" / kind).rglob("2014-*.json"):
            relative = path.relative_to(ROOT / "data/generated")
            target = public / relative.with_suffix(".json.gz")
            assert load(target) == load(path), relative
            count += 1
        assert count == expected, (kind, count, expected)
        counts[kind] = count
    for kind in ["investors", "credit"]:
        source = load(ROOT / f"data/{kind}/index.json")
        assert load(public / f"{kind}/index.json") == source, kind
        counts[kind] = sum(row["date"].startswith("2014-") for row in source["history"])
    load_sector_source = load_sector_listing if (public / "stock-history/korea-daily/index.json").is_file() else load
    for path in (ROOT / "data/sectors/daily").glob("*.json.gz"):
        assert load_published_sector_day(public / "sectors", path.name[:10]) == load_sector_source(path), path.name
    assert load(public / "sectors/index.json") == load_sector_source(ROOT / "data/sectors/index.json"), "latest sector snapshot"
    counts["sector_listing_archives"] = len(list((ROOT / "data/sectors/daily").glob("*.json.gz")))
    source = load(ROOT / "data/semiconductor/index.json")
    by_ticker = {row["ticker"]: row for row in load(public / "semiconductor/index.json")["stocks"]}
    for row in source["stocks"]:
        assert by_ticker[row["ticker"]]["history"] == row["history"], row["ticker"]
    counts["semiconductor_histories"] = len(by_ticker)
    histories = information = price_points = 0
    for path in (ROOT / "data/stock-history").glob("*.gz"):
        for ticker, value in load(path).items():
            filename = quote(ticker, safe="").replace("%", "~") + ".json.gz"
            published = load(public / "stock-history" / filename)
            assert published["ticker"] == ticker and published["currency"] == value["currency"], ticker
            assert published["prices"] == value["prices"], ticker
            expected = dict(value)
            if 'prior_snapshots' in expected:
                primary_dates = {point[0] for point in value['prices']}
                expected['prior_snapshots'] = [curve for curve in value['prior_snapshots']
                    if value['currency'] == curve['currency'] == 'KRW' and curve.get('complete_history')
                    and any(point[0] not in primary_dates for point in curve['prices'])]
            assert published == expected, (ticker, 'Price archive values or metadata changed')
            year_prices = {point[0]: point for point in published['prices'] if point[0].startswith('2014-')}
            if ticker in source_calendar:
                original = source_calendar[ticker]
                assert published['currency'] == original['currency'], (ticker, 'Original 2014 currency changed')
                assert set(original['dates']) <= year_prices.keys(), (ticker, 'Verified source sessions missing from the public curve', sorted(set(original['dates'])-year_prices.keys()))
                verified_source_calendars.add(ticker)
            market = markets.get(ticker, 'taiwan' if ticker.endswith(('.TW', '.TWO')) else None)
            if market in allowed:
                for curve in [published, *published.get('prior_snapshots', [])]:
                    assert all(not point[0].startswith('2014-') or point[0] in allowed[market] for point in curve['prices']), (ticker, 'Closed-session value in regular public curve')
            if ticker in saturday_prices:
                assert published['currency'] == 'TWD' and year_prices.get('2014-12-27') == saturday_prices[ticker], (ticker, 'Official Saturday not retained in the public primary curve')
                verified_saturdays.add(ticker)
            price_points += len(published['prices']) + sum(len(curve['prices']) for curve in published.get('prior_snapshots', []))
            assert all(not row.get("rejected_daily_granularity") for row in published.get("prior_snapshots", [])), ticker
            histories += 1
    for path in (ROOT / "data/stock-information").glob("*.gz"):
        for ticker, value in load(path).items():
            filename = quote(ticker, safe="").replace("%", "~") + ".json.gz"
            published = load(public / "stock-information" / filename)
            assert published["ticker"] == ticker, ticker
            for field in ["financials", "quote", "metrics", "historical_2014_coverage"]:
                assert published.get(field) == value.get(field), (ticker, field)
            information += 1
    counts.update(continuous_stock_histories=histories, information_snapshots=information, losslessly_verified_price_points=price_points)
    assert verified_source_calendars == set(source_calendar)
    assert verified_saturdays == set(saturday_prices)
    counts.update(verified_source_2014_price_calendars=len(verified_source_calendars), verified_taiwan_saturday_prices=len(verified_saturdays))
    rebound_paths = list((ROOT / "data/rebounds/reports/korea").glob("2014_*/*.json"))
    for path in rebound_paths:
        relative = path.relative_to(ROOT / "data/rebounds/reports")
        assert load(public / "rebounds" / relative) == load(path), relative
    counts["rebound_sessions"] = len(rebound_paths)
    assert counts["rebound_sessions"] == 245
    assert load(public / "chart-replay/markets.json") == load(ROOT / "data/chart-replay/markets.json")
    if args.artifact:
        artifact = args.artifact.resolve()
        assert artifact.is_relative_to(ROOT), artifact
        files = [path for path in artifact.rglob("*") if path.is_file()]
        assert (artifact / "index.html").exists()
        counts.update(artifact_files=len(files), artifact_bytes=sum(path.stat().st_size for path in files))
        assert counts["artifact_bytes"] < 1024**3, counts
    write_json(ROOT / "data/information-audit/2014/publication.json", counts)
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
