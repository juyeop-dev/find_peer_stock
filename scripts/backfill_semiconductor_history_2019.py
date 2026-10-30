"""Extend curated semiconductor prices using verified original Yahoo histories."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import quote, urlencode

import generate_semiconductor_data as semi
import stock_chart_history as charts
from extend_stock_history_2023 import join_prices


def fetch(stock):
    ticker = stock["ticker"]
    path = semi.ROOT / "data/tmp_2019/semiconductor" / f"{ticker}.json"
    if path.exists():
        raw = path.read_bytes()
    else:
        now = datetime.now(timezone.utc)
        params = {"period1": int(datetime(2018, 12, 20, tzinfo=timezone.utc).timestamp()),
                  "period2": int(now.timestamp()), "interval": "1d"}
        payload = semi.fetch_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker)}?{urlencode(params)}")
        raw = json.dumps(payload, ensure_ascii=False).encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    payload = json.loads(raw)
    parsed = charts.parse_yahoo(payload, ticker)
    if parsed["currency"] != "KRW" or len(parsed["prices"]) < 2:
        raise ValueError(f"Invalid Korean original: {ticker}")
    if stock.get("historical_2019_extension", {}).get("sha256") == hashlib.sha256(raw).hexdigest():
        return stock
    result = payload["chart"]["result"][0]
    volumes = result["indicators"]["quote"][0].get("volume", [])
    by_date = {datetime.fromtimestamp(stamp, semi.KST).date().isoformat(): volumes[i] if i < len(volumes) else None
               for i, stamp in enumerate(result["timestamp"])}
    history = [{"date": day, "close": round(close, 2), "adjusted_close": round(adjusted, 2),
                "volume": int(by_date[day]) if by_date.get(day) is not None else None}
               for day, close, adjusted in parsed["prices"]]
    old = stock["history"]
    compact = lambda rows: [[row["date"], row["close"], row["adjusted_close"]] for row in rows]
    joined = join_prices({"ticker": ticker, "currency": "KRW", "prices": compact(old)},
                         {"ticker": ticker, "currency": "KRW", "prices": compact(history)}, start="2018-12-20", split_only=False)
    value = dict(stock)
    if joined:
        value["history"] = [point for point in history if point["date"] < old[0]["date"]] + old
        mode = "verified_prefix"
    else:
        value["history"] = history
        value["prior_history_snapshots"] = stock.get("prior_history_snapshots", []) + [{
            "source": "Previous published semiconductor daily history", "history": old,
            "reason": "Retain original observations separately from revised provider adjustments"}]
        mode = "coherent_original_with_prior_snapshot"
    value["historical_2019_extension"] = {"source": "Yahoo Finance daily chart", "source_symbol": ticker,
        "sha256": hashlib.sha256(raw).hexdigest(), "cache": str(path.relative_to(semi.ROOT)), "mode": mode,
        "fetched_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}
    return value


def main():
    previous = json.loads(semi.SOURCE.read_bytes())
    with ThreadPoolExecutor(max_workers=6) as pool:
        stocks = list(pool.map(fetch, previous["stocks"]))
    now = datetime.now(timezone.utc).isoformat()
    semi.write_json(semi.SOURCE, {**previous, "history_updated_at": now, "stocks": stocks})
    semi.write_json(semi.ROOT / "data/information-audit/2019/semiconductor-history.json", {
        "total": len(stocks), "validated_at": now,
        "results": [{"ticker": row["ticker"], "first_price": row["history"][0]["date"],
                     **row["historical_2019_extension"]} for row in stocks]})
    print(f"Updated {len(stocks)} verified semiconductor histories; all other stock fields retained", flush=True)


if __name__ == "__main__":
    main()
