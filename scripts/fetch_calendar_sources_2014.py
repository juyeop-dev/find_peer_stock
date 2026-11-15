"""Preserve original exchange calendars before collecting the 2014 sessions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import ssl
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'taiwan-saturday-supplement': 'https://www.twsa.org.tw/B01/doc/104Q1.pdf',
    'taiwan': 'https://www.tpex.org.tw/storage/en-us/web/bulletin/trading_date/trading_date_103.htm',
    'taiwan-suspended': 'https://wwwc.twse.com.tw/en/clearing/suspended.html',
    'us': 'https://ir.theice.com/press/news-details/2013/NYSE-Euronext-Announces-2015-Holiday-Calendar-and-Early-Closings/default.aspx',
    'china': 'https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988725.shtml',
    'japan-holidays': 'https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv',
    'europe': 'https://www.euronext.com/en/about/media/euronext-press-releases/nyse-euronext-announces-its-2014-holiday-calendar-and-early',
    'xetra': 'https://www.xetra.com/resource/blob/281576/967747fbc75fa120c2142e05d2e40711/data/trading-calendar-2014.pdf',
    'eurex': 'https://www.xetra.com/resource/blob/249120/6fadad3fe12a3cc3fa392442532d4414/tradingcalendar_2014_en-data.pdf',
}


def fetch(item):
    name, url = item
    folder = ROOT / 'data/tmp_2014/sources'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name + ('.pdf' if '.pdf' in url else '.csv' if '.csv' in url else '.html'))
    try:
        if not path.exists():
            context = ssl.create_default_context()
            # Older exchange CA chains omit SKI. Keep CA and hostname checks;
            # use the pre-Python-3.13 certificate-chain compatibility mode.
            if name.startswith('taiwan'):
                context.verify_flags &= ~ssl.VERIFY_X509_STRICT
            with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0 historical market calendar research'}), timeout=45, context=context) as response:
                raw = response.read()
            if len(raw) < 200:
                raise ValueError('Empty source')
            path.write_bytes(raw)
        raw = path.read_bytes()
        result = {'url': url, 'path': path.relative_to(ROOT).as_posix(),
                  'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                  'checked_at': datetime.now(timezone.utc).isoformat()}
    except Exception as error:
        result = {'url': url, 'error': f'{type(error).__name__}: {error}'}
    print(name, result.get('bytes', result.get('error')), flush=True)
    return name, result


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = dict(pool.map(fetch, SOURCES.items()))
    (ROOT / 'data/tmp_2014/sources/manifest.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
