"""Extend curated semiconductor prices using verified original Yahoo histories."""
from concurrent.futures import ThreadPoolExecutor
import argparse
from dataclasses import asdict
from pathlib import Path
from collection_request import collection_request
from history_policy import DEFAULT_POLICY
from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import quote, urlencode

import generate_semiconductor_data as semi
import stock_chart_history as charts
from extend_stock_history_2023 import join_prices


def fetch(stock, request=None):
    request = request or collection_request(year=2014, root=semi.ROOT, through_present=True)
    extension_key = f"historical_{request.key}_extension"
    ticker = stock["ticker"]
    path = request.state / "semiconductor" / f"{ticker}.json"
    if path.exists():
        raw = path.read_bytes()
    else:
        now = datetime.now(timezone.utc)
        params = {"period1": int(datetime.fromisoformat(request.reference_start).replace(tzinfo=timezone.utc).timestamp()),
                  "period2": min(int(now.timestamp()), int(datetime.fromisoformat(request.end).replace(tzinfo=timezone.utc).timestamp()) + 86400), "interval": "1d"}
        payload = semi.fetch_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker)}?{urlencode(params)}")
        raw = json.dumps(payload, ensure_ascii=False).encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    payload = json.loads(raw)
    parsed = charts.parse_yahoo(payload, ticker)
    parsed["prices"] = [point for point in parsed["prices"] if request.reference_start <= point[0] <= request.end]
    if parsed["currency"] != "KRW" or len(parsed["prices"]) < 2:
        raise ValueError(f"Invalid Korean original: {ticker}")
    if (stock.get(extension_key, {}).get("sha256") == hashlib.sha256(raw).hexdigest()
            and stock.get(extension_key, {}).get("requested_start", request.reference_start) == request.reference_start):
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
                         {"ticker": ticker, "currency": "KRW", "prices": compact(history)}, start=request.reference_start, split_only=False)
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
    value[extension_key] = {"source": "Yahoo Finance daily chart", "source_symbol": ticker,
        "requested_start": request.reference_start, "requested_end": request.end,
        "sha256": hashlib.sha256(raw).hexdigest(), "cache": str(path.relative_to(semi.ROOT)), "mode": mode,
        "fetched_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}
    return value


def main(argv=None, *, year=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=year)
    parser.add_argument("--history-config", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        request = collection_request(year=args.year, config=args.history_config, root=semi.ROOT, through_present=args.year is not None)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.dry_run:
        print(json.dumps(asdict(request), default=str)); return
    extension_key = f"historical_{request.key}_extension"
    previous = semi.load_existing(semi.SOURCE)
    with ThreadPoolExecutor(max_workers=6) as pool:
        stocks = list(pool.map(lambda stock: fetch(stock, request), previous["stocks"]))
    now = datetime.now(timezone.utc).isoformat()
    semi.write_json(semi.SOURCE, {**previous, "history_updated_at": now, "stocks": stocks})
    semi.write_json(request.audit / "semiconductor-history.json", {
        "total": len(stocks), "validated_at": now,
        "results": [{"ticker": row["ticker"], "first_price": row["history"][0]["date"],
                     **row[extension_key]} for row in stocks]})
    print(f"Updated {len(stocks)} verified semiconductor histories; all other stock fields retained", flush=True)


if __name__ == "__main__":
    main()
