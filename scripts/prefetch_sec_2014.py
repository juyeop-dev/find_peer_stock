"""Cache original SEC frames without changing any published information."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from urllib.error import HTTPError

from backfill_sec_financials_2014 import cached, PERIODS, TAGS, CACHE


def main():
    cached('https://www.sec.gov/files/company_tickers_exchange.json')
    urls = sorted({f'https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{period}.json'
                   for tags in TAGS.values() for tag in tags for period in PERIODS})
    def fetch(url):
        try:
            value = cached(url)
            return {'url': url, 'facts': len(value.get('data', [])), 'status': 'cached_original'}
        except HTTPError as error:
            if error.code != 404:
                raise
            return {'url': url, 'status': 'original_404'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(fetch, urls))
    proof = {'checked_at': datetime.now(timezone.utc).isoformat(), 'frames': results,
             'scope': 'Original source cache only; no stock financials merged or published'}
    (CACHE / 'prefetch.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
    print({'cached_frames': sum(row['status'] == 'cached_original' for row in results),
           'original_404': sum(row['status'] == 'original_404' for row in results)}, flush=True)


if __name__ == '__main__':
    main()
