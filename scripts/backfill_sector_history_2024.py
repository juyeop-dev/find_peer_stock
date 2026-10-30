"""Recover missing H1-2024 sector observations without rewriting corrected H2."""
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import gzip
import json

from backfill_korean_new_highs import cached_request, history_url, parse_history
from backfill_sector_history_2024_h2 import reconstruct
from stock_chart_history import ROOT, write_json


def eligible_on_day(stock, history, first_trade_dates, day):
    first = first_trade_dates.get(stock["ticker"])
    # Actual observations take precedence over an inconsistent listing date.
    return not first or first <= str(day) or any(observed <= day for observed in history)


def main(year=2024, end_before="2024-07-01", audit_scope="2024"):
    directory = ROOT / "data/sectors"
    latest = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    sessions = sorted(date.fromisoformat(p.stem) for p in (ROOT / "data/new-highs/reports/korea").glob(f"{year}-*.json") if end_before is None or p.stem < end_before)
    if not sessions:
        raise ValueError(f"Collect validated Korean {year} calendar reports first")
    start, end = sessions[0] - timedelta(days=380), sessions[-1]
    def fetch(stock):
        raw = cached_request(history_url(stock["code"], start, end), 30, ROOT / "data/tmp_korean_history")
        return stock["ticker"], parse_history(raw, code=stock["code"], start=start, end=end)
    with ThreadPoolExecutor(max_workers=12) as pool:
        histories = dict(pool.map(fetch, latest["stocks"]))
    first_trade_dates = {}
    for pack in (ROOT / "data/stock-history").glob("*.json.gz"):
        for ticker, value in json.loads(gzip.decompress(pack.read_bytes())).items():
            first = value.get("first_trade_date")
            if value.get("ticker") == ticker and value.get("currency") == "KRW" and first:
                date.fromisoformat(first)
                first_trade_dates[ticker] = first
    fetched_at = datetime.now(timezone.utc).isoformat()
    count = 0
    for day in sessions:
        path = directory / "daily" / f"{day}.json.gz"
        if path.exists():
            continue
        stocks = []
        for stock in latest["stocks"]:
            value = reconstruct(stock, histories[stock["ticker"]], day)
            if value:
                value.pop("market_cap_date", None)
                value.pop("monetary_source", None)
                stocks.append(value)
        eligible = sum(eligible_on_day(stock, histories[stock["ticker"]], first_trade_dates, day) for stock in latest["stocks"])
        if len(stocks) < eligible * .75:
            raise ValueError(f"Incomplete historical session {day}: {len(stocks)}/{eligible} eligible listings")
        snapshot = {"schema_version": 1, "market": "korea", "currency": "KRW", "date": str(day), "fetched_at": fetched_at,
            "source": "Naver Finance historical daily bars / current sector classification", "source_url": "https://stock.naver.com/",
            "universe": "현재 KOSPI·KOSDAQ 보통주 분류에서 당시 거래가 확인된 종목 · 상장폐지 종목 제외", "received": len(histories),
            "excluded": {"no_session": len(histories) - len(stocks)}, "stale_count": 0, "stocks": stocks,
            "reconstruction": {"classification_date": latest["date"], "classification_source": latest["source_url"],
                "note": "현재 업종 분류 기준으로 과거 조정 주가를 재구성한 자료입니다. 당시 구성 종목 전체와 다를 수 있습니다. 거래대금과 시가총액은 KRX 일별 확정 자료로 보완합니다.",
                "returns": "Observed adjusted closes; prior trading session on or before calendar lookback; no extrapolation",
                "coverage": {"eligible_listings": eligible, "observed_listings": len(stocks), "minimum_ratio": .75,
                             "basis": "Verified first-trade dates exclude later listings; unknown dates remain eligible"}}}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".gz.tmp")
        temporary.write_bytes(gzip.compress(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(), mtime=0))
        temporary.replace(path)
        count += 1
    write_json(ROOT / f"data/information-audit/{audit_scope}/sector-progress.json", {"start": str(sessions[0]), "end": str(end), "added": count,
        "source_start": str(start), "classification_date": latest["date"], "history_symbols": len(histories)})
    print(f"Added {count} {year} sector observations; existing archives retained", flush=True)


if __name__ == "__main__":
    main()
