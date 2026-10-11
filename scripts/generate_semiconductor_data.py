"""Build curated Korean semiconductor history and a frequently refreshed quote snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed" / "semiconductor_stocks.json"
SOURCE = ROOT / "data" / "semiconductor" / "index.json"
PUBLISHED = ROOT / "frontend" / "public" / "data" / "semiconductor" / "index.json"
KST = ZoneInfo("Asia/Seoul")
USER_AGENT = "Mozilla/5.0 (compatible; StockPeerSite/1.0)"


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=18) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"Expected JSON object from {url}")
    return result


def numeric(value: object) -> float | None:
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fetch_history(ticker: str) -> list[dict]:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(ticker)}?range=2y&interval=1d")
    chart = fetch_json(url).get("chart") or {}
    if chart.get("error") or not chart.get("result"):
        raise ValueError(f"{ticker}: Yahoo chart unavailable: {chart.get('error')}")
    result = chart["result"][0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quotes = (indicators.get("quote") or [{}])[0]
    adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose") or []
    closes = quotes.get("close") or []
    volumes = quotes.get("volume") or []
    history = []
    for i, timestamp in enumerate(timestamps):
        close = numeric(closes[i]) if i < len(closes) else None
        if close is None or close <= 0:
            continue
        adjusted_close = numeric(adjusted[i]) if i < len(adjusted) else None
        volume = numeric(volumes[i]) if i < len(volumes) else None
        history.append({
            "date": datetime.fromtimestamp(timestamp, tz=KST).date().isoformat(),
            "close": round(close, 2),
            "adjusted_close": round(adjusted_close or close, 2),
            "volume": int(volume) if volume is not None else None,
        })
    if len(history) < 2:
        raise ValueError(f"{ticker}: fewer than two usable daily prices")
    return history


def fetch_financials(code: str, period_type: str) -> list[dict]:
    url = f"https://m.stock.naver.com/api/stock/{code}/finance/{period_type}"
    info = fetch_json(url).get("financeInfo") or {}
    titles = info.get("trTitleList") or []
    row_map = {row.get("title"): row.get("columns") or {} for row in info.get("rowList") or []}
    metrics = {"revenue": row_map.get("매출액", {}),
               "operating_income": row_map.get("영업이익", {}),
               "net_income": row_map.get("당기순이익", {})}
    result = []
    for period in titles:
        if period.get("isConsensus") != "N":
            continue
        key = period.get("key")
        if not key:
            continue
        values = {name: numeric(columns.get(key, {}).get("value")) for name, columns in metrics.items()}
        if any(value is not None for value in values.values()):
            result.append({"period": period.get("title") or key,
                           "type": "annual" if period_type == "annual" else "quarterly",
                           **values})
    return result


def fetch_metrics(code: str) -> tuple[str | None, dict]:
    url = f"https://m.stock.naver.com/api/stock/{code}/integration"
    payload = fetch_json(url)
    by_code = {entry.get("code"): entry.get("value") for entry in payload.get("totalInfos") or []}
    metrics = {key: by_code.get(key) for key in (
        "marketValue", "per", "pbr", "eps", "bps", "dividendYieldRatio",
        "highPriceOf52Weeks", "lowPriceOf52Weeks", "accumulatedTradingVolume",
    )}
    return payload.get("stockName"), metrics


def load_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def collect_full_entry(seed: dict, previous: dict | None) -> dict:
    ticker = seed["ticker"]
    code = ticker.split(".", 1)[0]
    entry = {**seed, "code": code, "market": "KOSPI" if ticker.endswith(".KS") else "KOSDAQ"}
    errors = []
    try:
        entry["history"] = fetch_history(ticker)
    except Exception as exc:
        errors.append(f"history: {exc}")
        entry["history"] = (previous or {}).get("history") or []
    for period_type in ("annual", "quarter"):
        key = "annual_financials" if period_type == "annual" else "quarterly_financials"
        try:
            entry[key] = fetch_financials(code, period_type)
        except Exception as exc:
            errors.append(f"{period_type}: {exc}")
            entry[key] = (previous or {}).get(key) or []
    try:
        name, metrics = fetch_metrics(code)
        entry["name"] = name or (previous or {}).get("name") or ticker
        entry["metrics"] = metrics
    except Exception as exc:
        errors.append(f"metrics: {exc}")
        entry["name"] = (previous or {}).get("name") or ticker
        entry["metrics"] = (previous or {}).get("metrics") or {}
    entry["data_errors"] = errors
    return entry


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def generate_full(seed_path: Path = SEED, output_path: Path = SOURCE, *, force: bool = False,
                  now: datetime | None = None) -> dict:
    now = now or datetime.now(tz=KST)
    existing = load_existing(output_path)
    seed_hash = hashlib.sha256(seed_path.read_bytes()).hexdigest()
    previous_date = str(existing.get("generated_at") or "")[:10]
    if (not force and existing.get("stocks") and existing.get("seed_hash") == seed_hash
            and (now.time() < time(16, 30) or previous_date == now.date().isoformat())):
        print(f"Retaining semiconductor history from {existing.get('generated_at')}")
        return existing
    seeds = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(seeds, list) or not seeds:
        raise ValueError("Semiconductor seed must contain stocks")
    prior = {row["ticker"]: row for row in existing.get("stocks") or []}
    rows = [None] * len(seeds)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(collect_full_entry, seed, prior.get(seed["ticker"])): index
                   for index, seed in enumerate(seeds)}
        for future in as_completed(futures):
            index = futures[future]
            rows[index] = future.result()
    usable = sum(bool(row["history"]) for row in rows)
    if usable < max(1, int(len(rows) * 0.8)):
        raise RuntimeError(f"Only {usable}/{len(rows)} semiconductor histories available; published data preserved")
    payload = {"generated_at": now.isoformat(), "seed_hash": seed_hash,
               "history_source": "Yahoo Finance daily chart",
               "financial_source": "Naver Finance annual/quarterly (actual only)",
               "financial_unit": "억원", "coverage": "curated", "stocks": rows}
    write_json(output_path, payload)
    print(f"Semiconductor history: {usable}/{len(rows)} stocks with daily prices")
    return payload


def fetch_current_quote(code: str) -> dict:
    payload = fetch_json(f"https://m.stock.naver.com/api/stock/{code}/basic")
    price = numeric(payload.get("closePrice"))
    if price is None or price <= 0:
        raise ValueError(f"{code}: current price unavailable")
    return {"price": price, "change": numeric(payload.get("compareToPreviousClosePrice")),
            "change_pct": numeric(payload.get("fluctuationsRatio")),
            "provider_time": payload.get("localTradedAt"),
            "market_status": payload.get("marketStatus"),
            "market": payload.get("stockExchangeName"),
            "name": payload.get("stockName")}


def publish(source_path: Path = SOURCE, output_path: Path = PUBLISHED,
            *, now: datetime | None = None) -> dict:
    source = load_existing(source_path)
    if not source.get("stocks"):
        raise RuntimeError(f"No semiconductor source data at {source_path}")
    now = now or datetime.now(tz=KST)
    rows = [{**row} for row in source["stocks"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_current_quote, row["code"]): index for index, row in enumerate(rows)}
        for future in as_completed(futures):
            index = futures[future]
            row = rows[index]
            try:
                quote = future.result()
                if quote.get("market") in {"KOSPI", "KOSDAQ"}:
                    row["market"] = quote["market"]
                row["name"] = quote.get("name") or row["name"]
                row["quote"] = {key: value for key, value in quote.items() if key not in {"name", "market"}}
                row["quote"].update(status="ok", fetched_at=now.isoformat(), source="Naver Finance")
            except Exception as exc:
                latest = (row.get("history") or [{}])[-1]
                row["quote"] = {"price": latest.get("close"), "change": None, "change_pct": None,
                                "provider_time": latest.get("date"), "market_status": None,
                                "status": "stale", "fetched_at": now.isoformat(),
                                "source": "Yahoo Finance last daily close", "error": str(exc)}
    payload = {**source, "quoted_at": now.isoformat(), "quote_source": "Naver Finance basic", "stocks": rows}
    write_json(output_path, payload)
    print(f"Semiconductor quotes: {sum(row['quote']['status'] == 'ok' for row in rows)}/{len(rows)} current")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("full", "publish"))
    parser.add_argument("--seed", type=Path, default=SEED)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=PUBLISHED)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.mode == "full":
        generate_full(args.seed, args.source, force=args.force)
    else:
        publish(args.source, args.output)


if __name__ == "__main__":
    main()
