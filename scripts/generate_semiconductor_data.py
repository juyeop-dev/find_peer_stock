"""Build curated Korean semiconductor history and a frequently refreshed quote snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed" / "semiconductor_stocks.json"
CATEGORIES = ROOT / "data" / "seed" / "semiconductor_categories.json"
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


def fetch_recent_naver_prices(code: str) -> list[dict]:
    """Fetch recent trading dates that Yahoo's daily chart can omit."""
    url = f"https://m.stock.naver.com/api/stock/{code}/price?pageSize=40&page=1"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=18) as response:
        rows = json.loads(response.read().decode("utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"{code}: Naver daily prices unavailable")
    prices = []
    for row in rows:
        date = row.get("localTradedAt")
        close = numeric(row.get("closePrice"))
        if not isinstance(date, str) or len(date) != 10 or close is None or close <= 0:
            continue
        volume = numeric(row.get("accumulatedTradingVolume"))
        prices.append({"date": date, "close": round(close, 2),
                       "volume": int(volume) if volume is not None else None})
    if not prices:
        raise ValueError(f"{code}: no usable Naver daily prices")
    return prices


def fill_missing_recent_prices(history: list[dict], recent: list[dict]) -> list[dict]:
    """Keep Yahoo adjustments and insert trading days missing from its daily feed."""
    merged = {row["date"]: row for row in history}
    for row in recent:
        date = row["date"]
        if date in merged:
            continue
        nearby = next((item for item in reversed(history) if item["date"] <= date), history[-1])
        factor = nearby["adjusted_close"] / nearby["close"]
        merged[date] = {**row, "adjusted_close": round(row["close"] * factor, 2)}
    return [merged[date] for date in sorted(merged)]


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


def build_recent_financials(quarterly: list[dict], annual: list[dict]) -> dict:
    """Use four consecutive reported standalone quarters, never annualize a partial year."""
    def quarter_index(period: str) -> int | None:
        match = re.fullmatch(r"(\d{4})\.(03|06|09|12)\.?", period)
        return int(match[1]) * 4 + int(match[2]) // 3 - 1 if match else None

    def period_label(index: int) -> str:
        return f"{index // 4}년 {index % 4 + 1}Q"

    def complete_sum(rows: list[dict], key: str) -> float | None:
        values = [numeric(row.get(key)) for row in rows]
        return round(sum(values), 2) if all(value is not None for value in values) else None

    quarters = {index: row for row in quarterly
                if row.get("type") == "quarterly"
                and (index := quarter_index(str(row.get("period") or ""))) is not None}
    latest = max(quarters, default=None)
    latest_period = quarters[latest]["period"] if latest is not None else None
    indices = list(range(latest - 3, latest + 1)) if latest is not None else []
    if indices and all(index in quarters for index in indices):
        rows = [quarters[index] for index in indices]
        revenue = complete_sum(rows, "revenue")
        operating_income = complete_sum(rows, "operating_income")
        return {"basis": "ttm", "period_label": f"{period_label(indices[0])}~{period_label(indices[-1])}",
                "periods": [row["period"] for row in rows], "latest_reported_period": latest_period,
                "revenue": revenue, "operating_income": operating_income,
                "reason": "최근 4개 분기 중 누락된 지표는 표시하지 않습니다."
                          if revenue is None or operating_income is None else None}

    # Keep a fallback explicitly labelled as a fiscal year; do not mix periods between metrics.
    years = [row for row in annual if row.get("type") == "annual"
             and re.fullmatch(r"\d{4}\.\d{2}\.?", str(row.get("period") or ""))
             and any(numeric(row.get(key)) is not None for key in ("revenue", "operating_income"))]
    if years:
        row = max(years, key=lambda item: item["period"])
        date = row["period"].rstrip(".")
        label = f"{date[:4]}년 연간" if date.endswith(".12") else f"{date} 결산 연간"
        return {"basis": "annual", "period_label": label, "periods": [row["period"]],
                "latest_reported_period": latest_period, "revenue": numeric(row.get("revenue")),
                "operating_income": numeric(row.get("operating_income")),
                "reason": "최신 발표 분기까지 연속된 4개 분기가 부족해 최근 결산 연간 실적을 표시합니다."}
    return {"basis": "unavailable", "period_label": "자료 부족", "periods": [],
            "latest_reported_period": latest_period, "revenue": None, "operating_income": None,
            "reason": "최근 1년 실적을 계산할 발표 자료가 부족합니다."}


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


def seed_fingerprint(seed_path: Path = SEED, categories_path: Path = CATEGORIES) -> str:
    digest = hashlib.sha256()
    digest.update(seed_path.read_bytes())
    digest.update(categories_path.read_bytes())
    return digest.hexdigest()


def classified_seeds(seed_path: Path = SEED, categories_path: Path = CATEGORIES) -> list[dict]:
    seeds = json.loads(seed_path.read_text(encoding="utf-8"))
    categories = json.loads(categories_path.read_text(encoding="utf-8"))
    if not isinstance(seeds, list) or not seeds or not isinstance(categories, list) or not categories:
        raise ValueError("Semiconductor seeds and categories must be nonempty lists")
    by_ticker = {seed["ticker"]: {**seed, "classifications": []} for seed in seeds}
    if len(by_ticker) != len(seeds):
        raise ValueError("Duplicate semiconductor ticker")
    for group in categories:
        classification = {key: group[key] for key in ("major", "middle", "minor")}
        members = group.get("image", []) + group.get("additional", [])
        if not members or len(members) != len(set(members)):
            raise ValueError(f"Empty or duplicate members in {classification}")
        for ticker in members:
            if ticker not in by_ticker:
                raise ValueError(f"Unknown semiconductor ticker in categories: {ticker}")
            if classification in by_ticker[ticker]["classifications"]:
                raise ValueError(f"Duplicate classification for {ticker}: {classification}")
            by_ticker[ticker]["classifications"].append(classification)
    for seed in by_ticker.values():
        primary = next((item for item in seed["classifications"] if item["major"] != "핵심 연관 테마"),
                       seed["classifications"][0] if seed["classifications"] else None)
        if primary is None:
            raise ValueError(f"No primary semiconductor category for {seed['ticker']}")
        seed.update(primary)
    return list(by_ticker.values())


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
    if entry["history"]:
        try:
            entry["history"] = fill_missing_recent_prices(entry["history"], fetch_recent_naver_prices(code))
        except Exception as exc:
            errors.append(f"recent prices: {exc}")
    for period_type in ("annual", "quarter"):
        key = "annual_financials" if period_type == "annual" else "quarterly_financials"
        try:
            entry[key] = fetch_financials(code, period_type)
        except Exception as exc:
            errors.append(f"{period_type}: {exc}")
            entry[key] = (previous or {}).get(key) or []
    entry["recent_financials"] = build_recent_financials(entry["quarterly_financials"], entry["annual_financials"])
    try:
        name, metrics = fetch_metrics(code)
        entry["name"] = name or (previous or {}).get("name") or ticker
        entry["metrics"] = metrics
    except Exception as exc:
        errors.append(f"metrics: {exc}")
        entry["name"] = (previous or {}).get("name") or seed.get("name") or ticker
        entry["metrics"] = (previous or {}).get("metrics") or {}
    entry["data_errors"] = errors
    return entry


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def generate_full(seed_path: Path = SEED, output_path: Path = SOURCE, *, force: bool = False,
                  now: datetime | None = None, categories_path: Path = CATEGORIES) -> dict:
    now = now or datetime.now(tz=KST)
    existing = load_existing(output_path)
    seed_hash = seed_fingerprint(seed_path, categories_path)
    previous_date = str(existing.get("generated_at") or "")[:10]
    if (not force and existing.get("stocks") and existing.get("seed_hash") == seed_hash
            and (now.time() < time(16, 30) or previous_date == now.date().isoformat())):
        print(f"Retaining semiconductor history from {existing.get('generated_at')}")
        return existing
    seeds = classified_seeds(seed_path, categories_path)
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
               "history_source": "Yahoo Finance daily chart; missing recent dates filled from Naver Finance daily prices",
               "financial_source": "Naver Finance annual/quarterly (actual only)",
               "financial_unit": "억원", "coverage": "curated",
               "categories": [{key: group[key] for key in ("major", "middle", "minor")}
                              for group in json.loads(categories_path.read_text(encoding="utf-8"))],
               "stocks": rows}
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
    for row in rows:
        row["recent_financials"] = build_recent_financials(row.get("quarterly_financials", []), row.get("annual_financials", []))
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
    parser.add_argument("--categories", type=Path, default=CATEGORIES)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=PUBLISHED)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.mode == "full":
        generate_full(args.seed, args.source, force=args.force, categories_path=args.categories)
    else:
        publish(args.source, args.output)


if __name__ == "__main__":
    main()
