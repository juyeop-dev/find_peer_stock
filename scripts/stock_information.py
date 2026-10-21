"""Collect resumable, dated stock information and reported financials from July 2024 onward."""
from __future__ import annotations

import argparse
import calendar
import csv
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import stock_chart_history as charts

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "data/information-audit"
PACKS = ROOT / "data/stock-information"
START = "2024-07-01"
METRICS = {"revenue": "TotalRevenue", "operating_income": "OperatingIncome", "net_income": "NetIncome",
           "total_assets": "TotalAssets", "total_debt": "TotalDebt", "operating_cash_flow": "OperatingCashFlow", "free_cash_flow": "FreeCashFlow"}
COLUMNS = ["name", "description", "exchange", "type", "currency", "fundamental_currency_code", "close", "change", "time",
           "market_cap_basic", "price_earnings_ttm", "price_book_fq", "earnings_per_share_diluted_ttm", "dividends_yield_current",
           "price_52_week_high", "price_52_week_low", "sector", "industry", "number_of_employees",
           *[f"{key}_{period}" for period in ("fy", "fq", "fh") for key in ("fiscal_period_end", "total_revenue", "oper_income", "net_income")]]


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(str(value).replace(",", "").replace("%", ""))
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def fetch_json(url, body=None):
    request = Request(url, data=json.dumps(body).encode() if body is not None else None,
                      headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json", "Accept": "application/json"})
    with urlopen(request, timeout=18) as response:
        return json.load(response)


def symbols(row):
    ticker = row["ticker"]
    if ":" in ticker:
        return [ticker.replace("XETRA:", "XETR:")]
    code, _, suffix = ticker.rpartition(".")
    exchange = {"KS": "KRX", "KQ": "KRX", "T": "TSE", "TW": "TWSE", "TWO": "TPEX", "SS": "SSE", "SZ": "SZSE", "HK": "HKEX"}.get(suffix)
    if exchange:
        return [f"{exchange}:{int(code) if suffix == 'HK' else code}"]
    exchanges = [row["exchange"]] if row.get("exchange") in {"NASDAQ", "NYSE", "AMEX"} else ["NASDAQ", "NYSE", "AMEX"]
    return [f"{exchange}:{ticker}" for exchange in exchanges]


def open_database(folder=None):
    folder = folder or ROOT / "data/tmp_info_update"
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "information.sqlite")
    db.execute("CREATE TABLE IF NOT EXISTS information(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS scanner(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)")
    if not db.execute("SELECT count(*) FROM information").fetchone()[0]:
        for path in sorted(PACKS.glob("*.json.gz")):
            entries = json.loads(gzip.decompress(path.read_bytes()))
            db.executemany("INSERT OR REPLACE INTO information VALUES (?,?)", [(ticker, json.dumps(value, ensure_ascii=False)) for ticker, value in entries.items()])
        db.commit()
    return db


def fresh(timestamp, hours=24):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp)).total_seconds() < hours * 3600
    except (TypeError, ValueError):
        return False


def timestamp(value):
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return 0


def scan(db, rows, as_of, force=False):
    pending = []
    for row in rows:
        raw = db.execute("SELECT value FROM scanner WHERE ticker=?", (row["ticker"],)).fetchone()
        if force or not raw or not fresh(json.loads(raw[0]).get("fetched_at")):
            pending.append(row)
    for start in range(0, len(pending), 200):
        batch = pending[start:start + 200]
        requested = {symbol for row in batch for symbol in symbols(row)}
        payload = fetch_json("https://scanner.tradingview.com/global/scan", {"symbols": {"tickers": sorted(requested)}, "columns": COLUMNS, "range": [0, len(requested)], "price_conversion": {"to_symbol": True}})
        caps_payload = fetch_json("https://scanner.tradingview.com/global/scan", {"symbols": {"tickers": sorted(requested)}, "columns": ["market_cap_basic", "fundamental_currency_code"], "range": [0, len(requested)]})
        usd_caps = {item["s"]: number(item["d"][0]) for item in caps_payload.get("data", []) if item.get("s") in requested and len(item.get("d", [])) == 2 and item["d"][1] == "USD"}
        if not isinstance(payload.get("data"), list):
            raise ValueError("Malformed original stock scanner response")
        returned = {}
        for item in payload["data"]:
            if item.get("s") not in requested or len(item.get("d", [])) != len(COLUMNS) or item["s"] in returned:
                raise ValueError("Scanner listing identity, duplicate, or columns mismatch")
            returned[item["s"]] = {**dict(zip(COLUMNS, item["d"])), "symbol": item["s"], "market_cap_usd": usd_caps.get(item["s"])}
        now = datetime.now(timezone.utc).isoformat()
        for row in batch:
            matches = [returned[symbol] for symbol in symbols(row) if symbol in returned]
            value = {"fetched_at": now, "row": matches[0] if len(matches) == 1 else None}
            db.execute("INSERT OR REPLACE INTO scanner VALUES (?,?)", (row["ticker"], json.dumps(value, ensure_ascii=False)))
        db.commit()
        print(f"Stock scanner {min(start + len(batch), len(pending))}/{len(pending)}", flush=True)


def parse_yahoo_financials(payload, symbol, today):
    info = payload.get("timeseries") or {}
    if info.get("error"):
        raise ValueError("Financial source returned an error")
    rows = {}
    for series in info.get("result") or []:
        if series.get("meta", {}).get("symbol") != [symbol]:
            raise ValueError("Financial listing identity mismatch")
        for kind, prefix in (("annual", "annual"), ("quarterly", "quarterly")):
            for metric, field in METRICS.items():
                key = prefix + field
                for item in series.get(key, []):
                    day, currency = item.get("asOfDate", ""), item.get("currencyCode", "")
                    value = number((item.get("reportedValue") or {}).get("raw"))
                    if not START <= day <= today or value is None or not currency:
                        continue
                    if item.get("periodType") != ("12M" if kind == "annual" else "3M"):
                        continue
                    date.fromisoformat(day)
                    row = rows.setdefault((kind, day, currency), {"type": kind, "period_end": day, "currency": currency, "source": "Yahoo Finance reported financials"})
                    row[metric] = value
    return list(rows.values())


def parse_naver_financials(payload, kind, today):
    info = payload.get("financeInfo") or {}
    columns = {row["title"]: row.get("columns") or {} for row in info.get("rowList") or []}
    rows = []
    for period in info.get("trTitleList") or []:
        key = period.get("key", "")
        if period.get("isConsensus") != "N" or len(key) != 6 or not key.isdigit():
            continue
        year, month = int(key[:4]), int(key[4:])
        day = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
        if not START <= day <= today:
            continue
        row = {"type": kind, "period_end": day, "currency": "KRW", "source": "Naver Finance reported financials"}
        for metric, label in [("revenue", "매출액"), ("operating_income", "영업이익"), ("net_income", "당기순이익")]:
            value = number(columns.get(label, {}).get(key, {}).get("value"))
            row[metric] = value * 1e8 if value is not None else None
        if any(row.get(metric) is not None for metric in METRICS):
            rows.append(row)
    return rows


def scanner_information(ticker, raw, today):
    row = raw.get("row") or {}
    result = {"ticker": ticker, "requested_start": START, "fetched_at": raw["fetched_at"], "quote": None, "metrics": {}, "financials": [], "warnings": []}
    if not row:
        result["warnings"].append("현재 제공처에서 같은 거래소의 종목을 확인하지 못했습니다.")
        return result
    result["company"] = {key: row.get(key) for key in ("description", "sector", "industry", "number_of_employees")}
    result["source_symbol"] = row["symbol"]
    result["metrics"] = {key: number(row.get(column)) for key, column in [("per", "price_earnings_ttm"), ("pbr", "price_book_fq"), ("eps", "earnings_per_share_diluted_ttm"), ("dividend_yield", "dividends_yield_current"), ("high_52_week", "price_52_week_high"), ("low_52_week", "price_52_week_low")]}
    result["metrics_currency"] = row.get("fundamental_currency_code")
    price, change, stamp = number(row.get("close")), number(row.get("change")), number(row.get("time"))
    if price is not None and price > 0 and row.get("currency") and stamp and 0 < stamp <= datetime.now(timezone.utc).timestamp() + 86400:
        previous = price / (1 + change / 100) if change is not None and change > -100 else None
        result["quote"] = {"ticker": ticker, "price": price, "previous_close": previous, "change": price - previous if previous else None,
                           "change_pct": change, "currency": row["currency"], "source": "TradingView stock scanner", "provider_time": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                           "market_time": None, "fetched_at": raw["fetched_at"], "status": "ok", "market_cap": number(row.get("market_cap_basic")),
                           "market_cap_currency": row.get("fundamental_currency_code"), "market_cap_usd": row.get("market_cap_usd") or (number(row.get("market_cap_basic")) if row.get("fundamental_currency_code") == "USD" else None)}
        if (date.fromisoformat(today) - datetime.fromtimestamp(stamp, timezone.utc).date()).days > 7:
            result["quote"]["status"] = "stale"
            result["warnings"].append("제공처에 최근 7일 이내의 거래 자료가 없어 이전 제공 가격을 표시합니다.")
    currency = row.get("fundamental_currency_code")
    for kind, suffix in [("annual", "fy"), ("quarterly", "fq"), ("semiannual", "fh")]:
        stamp = number(row.get(f"fiscal_period_end_{suffix}"))
        if not stamp or not currency:
            continue
        day = datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()
        if not START <= day <= today:
            continue
        financial = {"type": kind, "period_end": day, "currency": currency, "source": "TradingView reported financials", **{metric: number(row.get(f"{field}_{suffix}")) for metric, field in [("revenue", "total_revenue"), ("operating_income", "oper_income"), ("net_income", "net_income")]}}
        if any(financial.get(key) is not None for key in METRICS):
            result["financials"].append(financial)
    return result


def collect_one(row, raw, today):
    info = scanner_information(row["ticker"], raw, today)
    fetched = []
    try:
        if row["market"] == "korea":
            code = row["ticker"].split(".")[0]
            for kind, endpoint in [("annual", "annual"), ("quarterly", "quarter")]:
                fetched.extend(parse_naver_financials(fetch_json(f"https://m.stock.naver.com/api/stock/{code}/finance/{endpoint}"), kind, today))
            # Retain full FY2024 balance-sheet/cash-flow reporting during the
            # daily refresh too. Naver's summary has only three income fields.
            symbol = charts.yahoo_symbol(row["ticker"])
            params = {"type": ",".join("annual" + field for field in METRICS.values()), "period1": 1719792000, "period2": 1735689600}
            historical = parse_yahoo_financials(fetch_json(f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{quote(symbol, safe='')}?{urlencode(params)}"), symbol, "2024-12-31")
            for statement in historical:
                old = next((item for item in fetched if item["type"] == statement["type"] and item["period_end"] == statement["period_end"]), None)
                if not old or (old["currency"] == statement["currency"] and all(old.get(metric) is None or statement.get(metric) is not None for metric in METRICS)):
                    fetched = [item for item in fetched if item is not old] + [statement]
        elif symbol := charts.yahoo_symbol(row["ticker"]):
            types = [prefix + field for prefix in ("annual", "quarterly") for field in METRICS.values()]
            params = {"type": ",".join(types), "period1": int(datetime.fromisoformat(START).replace(tzinfo=timezone.utc).timestamp()), "period2": int(datetime.now(timezone.utc).timestamp())}
            fetched = parse_yahoo_financials(fetch_json(f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{quote(symbol, safe='')}?{urlencode(params)}"), symbol, today)
    except Exception as exc:
        info["warnings"].append(f"과거 확정 실적 조회 실패: {type(exc).__name__}: {exc}")
        if isinstance(exc, HTTPError) and exc.code in {403, 429}:
            info["rate_limited"] = True
    # Keep each statement's original currency. Never splice converted metrics into a native statement.
    preferred = {(item["type"], item["period_end"]) for item in fetched}
    info["financials"] = sorted([item for item in info["financials"] if (item["type"], item["period_end"]) not in preferred] + fetched, key=lambda item: (item["period_end"], item["type"]))
    info["financials_fetched_at"] = datetime.now(timezone.utc).isoformat()
    if not info["financials"]:
        info["warnings"].append("2024년 하반기 이후 확정 실적이 제공되지 않습니다. 신규 상장·펀드·자료 미지원 여부를 원문에서 확인해 주세요.")
    info["financial_coverage"] = {"first_period": min((item["period_end"] for item in info["financials"]), default=None),
                                  "latest_period": max((item["period_end"] for item in info["financials"]), default=None),
                                  "note": "제공된 확정 회계기간만 표시합니다. 제공처가 제한한 과거 분기와 공시되지 않은 기간은 채우지 않습니다."}
    return info


def checkpoint(db, rows, history_db=None):
    results = []
    for row in rows:
        stored = db.execute("SELECT value FROM information WHERE ticker=?", (row["ticker"],)).fetchone()
        value = json.loads(stored[0]) if stored else {}
        prices = history_db.execute("SELECT value FROM history WHERE ticker=?", (row["ticker"],)).fetchone() if history_db else None
        history = json.loads(prices[0]) if prices else {}
        points = history.get("prices") or []
        start = points[0][0] if points else None
        recent_cutoff = (datetime.now(ZoneInfo("Asia/Seoul")).date() - timedelta(days=7)).isoformat()
        status = "missing" if len(points) < 2 else "no_recent_data" if points[-1][0] < recent_cutoff else "complete" if start and start <= START else "recent_listing" if history.get("first_trade_date", "") and history["first_trade_date"] > START else "limited"
        result = {**row, "status": "checked" if stored else "pending", "quote": bool(value.get("quote")), "financial_periods": len(value.get("financials", [])),
                  "financial_first": value.get("financial_coverage", {}).get("first_period"), "financial_latest": value.get("financial_coverage", {}).get("latest_period"),
                  "history_status": status, "history_start": start, "history_end": points[-1][0] if points else None,
                  "warnings": value.get("warnings", []), "historical_financials_warning": value.get("historical_financials_warning"), "price_points": len(points), "checked_at": value.get("financials_fetched_at")}
        results.append(result)
    AUDIT.mkdir(parents=True, exist_ok=True)
    with (AUDIT / "results.jsonl").open("w", encoding="utf-8") as output:
        for result in results:
            output.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    pending = [row for row in results if row["status"] == "pending"]
    fields = ["order", "ticker", "name", "market", "status", "quote", "financial_periods", "financial_first", "financial_latest", "history_status", "history_start", "history_end", "price_points", "historical_financials_warning", "warnings", "checked_at"]
    with (AUDIT / "results.csv").open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows({**row, "warnings": " / ".join(row.get("warnings", []))} for row in results)
    exceptions = [row for row in results if row["status"] == "checked" and (not row["quote"] or not row["financial_periods"] or row["warnings"] or row.get("historical_financials_warning") or row["history_status"] in {"limited", "missing", "no_recent_data"})]
    charts.write_json(AUDIT / "exceptions.json", exceptions)
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    stages = {"current_information": {"checked": len(rows) - len(pending), "next": pending[0] if pending else None}}
    financial_stage = ("financial_2024_h2", "financial_2024_h2_updates") if "financial_2024_h2_updates" in tables else ("financial_2025", "financial_2025_updates")
    for name, table in [financial_stage, ("daily_history", "history_2024h2_updates")]:
        done = {row[0] for row in db.execute(f"SELECT ticker FROM {table}")} if table in tables else set()
        todo = [row for row in rows if row["ticker"] not in done]
        stages[name] = {"checked": len(rows) - len(todo), "next": todo[0] if todo else None}
    next_step = next((name for name, value in stages.items() if value["next"]), None)
    commands = {"current_information": "python scripts/stock_information.py collect", "financial_2025": "python scripts/backfill_stock_information_2025.py", "financial_2024_h2": "python scripts/backfill_stock_information_2024_h2.py collect", "daily_history": "python scripts/refresh_stock_information_history.py"}
    charts.write_json(AUDIT / "progress.json", {"requested_start": START, "as_of": datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat(), "total": len(rows), "checked": len(rows) - len(pending),
        "quotes": sum(row["quote"] for row in results), "financials": sum(row["financial_periods"] > 0 for row in results), "history_counts": dict(Counter(row["history_status"] for row in results)),
        "phase": next_step or "audited_with_source_exceptions", "stages": stages,
        "next": stages[next_step]["next"] if next_step else None, "exceptions": len(exceptions), "resume": commands.get(next_step, "원본 미제공 예외를 exceptions.json의 종목 순서로 재확인"), "updated_at": datetime.now(timezone.utc).isoformat()})


def collect(db, rows, limit=None, force=False):
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    scan(db, rows, today)
    pending = []
    for row in rows:
        stored = db.execute("SELECT value FROM information WHERE ticker=?", (row["ticker"],)).fetchone()
        if force or not stored or not fresh(json.loads(stored[0]).get("financials_fetched_at"), hours=20):
            pending.append(row)
    if limit is not None:
        pending = pending[:limit]
    history_db = charts.database()
    with ThreadPoolExecutor(max_workers=4) as pool:
        for start in range(0, len(pending), 20):
            batch = pending[start:start + 20]
            raw = [json.loads(db.execute("SELECT value FROM scanner WHERE ticker=?", (row["ticker"],)).fetchone()[0]) for row in batch]
            futures = [pool.submit(collect_one, row, source, today) for row, source in zip(batch, raw)]
            for row, future in zip(batch, futures):
                value = future.result()
                old = db.execute("SELECT value FROM information WHERE ticker=?", (row["ticker"],)).fetchone()
                if old:
                    previous = json.loads(old[0])
                    keys = {(item["type"], item["period_end"]) for item in value["financials"]}
                    value["financials"] = sorted(value["financials"] + [item for item in previous.get("financials", []) if (item["type"], item["period_end"]) not in keys], key=lambda item: (item["period_end"], item["type"]))
                    for key in ["historical_financials_fetched_at", "historical_financials_warning", "historical_2024_h2_fetched_at", "historical_2024_h2_coverage"]:
                        if key in previous: value[key] = previous[key]
                    dates = sorted(item["period_end"] for item in value["financials"])
                    value["financial_coverage"].update(first_period=dates[0] if dates else None, latest_period=dates[-1] if dates else None)
                    if value["quote"] is None and previous.get("quote"):
                        value["quote"] = {**previous["quote"], "status": "stale"}
                db.execute("INSERT OR REPLACE INTO information VALUES (?,?)", (row["ticker"], json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)))
                db.commit()
                print(f"{row['order']}/{len(rows)} {row['ticker']} quote={bool(value['quote'])} statements={len(value['financials'])}", flush=True)
                if value.get("rate_limited"):
                    checkpoint(db, rows, history_db)
                    raise RuntimeError("Source access limited; checkpoint saved. Retry later.")
            if (start + len(batch)) % 200 == 0 or start + len(batch) == len(pending):
                checkpoint(db, rows, history_db)
    checkpoint(db, rows, history_db)
    history_db.close()


def export(db):
    PACKS.mkdir(parents=True, exist_ok=True)
    for shard in "0123456789abcdef":
        entries = {ticker: json.loads(raw) for ticker, raw in db.execute("SELECT ticker,value FROM information ORDER BY ticker") if hashlib.sha256(ticker.encode()).hexdigest()[0] == shard}
        body = json.dumps(entries, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        target = PACKS / f"{shard}.json.gz"
        temporary = target.with_suffix(".gz.tmp")
        temporary.write_bytes(gzip.compress(body, compresslevel=9, mtime=0))
        temporary.replace(target)
    print("Exported dated stock information", flush=True)


def publish():
    target = ROOT / "frontend/public/data/stock-information"
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    all_information = {}
    for path in sorted(PACKS.glob("*.json.gz")):
        entries = json.loads(gzip.decompress(path.read_bytes()))
        for ticker, value in entries.items():
            filename = quote(ticker, safe="").replace("%", "~") + ".json"
            charts.write_json(target / filename, value)
            all_information[ticker] = value
            count += 1
    sync_primary_snapshots(all_information)
    print(f"Published {count} stock information snapshots", flush=True)


def sync_primary_snapshots(information):
    """Update primary/peer quote copies without altering historical calendar reports."""
    def write_primary(path, value):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(path)
    def merge_quote(old, ticker):
        value = information.get(ticker, {}).get("quote")
        if not value or timestamp(value.get("fetched_at")) < timestamp(old.get("fetched_at")):
            return old
        if value.get("status") == "stale" and timestamp(value.get("provider_time") or value.get("provider_date")) < timestamp(old.get("provider_time") or old.get("provider_date") or old.get("market_time") or old.get("fetched_at")):
            return old
        # A scanner timestamp is a source bar time, not an exchange-verified live tick.
        from generate_static_data import get_market_state, market_state_fields
        return {**old, **value, **market_state_fields(get_market_state(ticker, datetime.now(ZoneInfo("Asia/Seoul"))), refresh_status="fetched"), "provider_time": value.get("provider_time"), "market_time": None,
                "refresh_status": "fetched", "error": None, "basis_label": "최근 제공 가격", "market_cap_source": "TradingView", "market_cap_fetched_at": value["fetched_at"]}
    for folder in [ROOT / "data/generated", ROOT / "frontend/public/data"]:
        stock_folder = folder / "stocks"
        for path in sorted(stock_folder.glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            ticker = value.get("company", {}).get("ticker")
            if not ticker:
                continue
            value["quote"] = merge_quote(value["quote"], ticker)
            value["generated_at"] = max([value.get("generated_at", ""), value["quote"].get("fetched_at", "")], key=timestamp)
            for group in value.get("peer_groups", []):
                for peer in group.get("peers", []):
                    peer["quote"] = merge_quote(peer["quote"], peer["company"]["ticker"])
            write_primary(path, value)
        path = folder / "index.json"
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            for stock in value.get("stocks", []):
                quote_value = information.get(stock["ticker"], {}).get("quote")
                if quote_value and timestamp(quote_value.get("fetched_at")) >= timestamp(value.get("generated_at")):
                    for key in ["market_cap", "market_cap_currency", "market_cap_usd"]:
                        stock[key] = quote_value.get(key)
            value["generated_at"] = max([value.get("generated_at", "")] + [item.get("quote", {}).get("fetched_at", "") for item in information.values() if item.get("quote")], key=timestamp)
            write_primary(path, value)
    source_path = ROOT / "data/semiconductor/index.json"
    if source_path.exists():
        from generate_semiconductor_data import build_recent_financials
        value = json.loads(source_path.read_text(encoding="utf-8"))
        for stock in value["stocks"]:
            info = information.get(stock["ticker"], {})
            for kind, key in [("annual", "annual_financials"), ("quarterly", "quarterly_financials")]:
                rows = {row["period"]: row for row in stock.get(key, [])}
                for row in info.get("financials", []):
                    if row["type"] == kind and row["currency"] == "KRW" and row["source"].startswith("Naver"):
                        period = row["period_end"][:7].replace("-", ".") + "."
                        if period in rows and timestamp(info.get("financials_fetched_at")) < timestamp(value.get("financials_updated_at") or value.get("generated_at")):
                            continue
                        rows[period] = {"period": period, "type": kind, **{metric: row.get(metric) / 1e8 if row.get(metric) is not None else None for metric in ["revenue", "operating_income", "net_income"]}}
                stock[key] = [rows[period] for period in sorted(rows)]
            stock["recent_financials"] = build_recent_financials(stock.get("quarterly_financials", []), stock.get("annual_financials", []))
        value["financials_updated_at"] = max([value.get("generated_at", "")] + [information.get(stock["ticker"], {}).get("financials_fetched_at", "") for stock in value["stocks"]], key=timestamp)
        charts.write_json(source_path, value)


def refresh_quotes(db, rows):
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    scan(db, rows, today, force=True)
    for row in rows:
        stored = db.execute("SELECT value FROM information WHERE ticker=?", (row["ticker"],)).fetchone()
        if not stored:
            continue
        value = json.loads(stored[0])
        raw = json.loads(db.execute("SELECT value FROM scanner WHERE ticker=?", (row["ticker"],)).fetchone()[0])
        latest = scanner_information(row["ticker"], raw, today)
        for key in ["fetched_at", "metrics", "metrics_currency", "company", "source_symbol"]:
            if key in latest:
                value[key] = latest[key]
        if latest["quote"]:
            value["quote"] = latest["quote"]
        value["warnings"] = list(dict.fromkeys(value["warnings"] + latest["warnings"]))
        db.execute("INSERT OR REPLACE INTO information VALUES (?,?)", (row["ticker"], json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)))
    db.commit()


def fill_daily_quotes(db):
    """Expose verified last daily values with dates when current quotes are unavailable."""
    history = charts.database()
    for ticker, raw in db.execute("SELECT ticker,value FROM information").fetchall():
        value = json.loads(raw)
        if value.get("quote"):
            continue
        stored = history.execute("SELECT value FROM history WHERE ticker=?", (ticker,)).fetchone()
        prices = json.loads(stored[0]) if stored else {}
        points = prices.get("prices") or []
        if not points or not prices.get("currency"):
            continue
        day, price, _ = points[-1]
        previous = points[-2][1] if len(points) > 1 else None
        value["quote"] = {"ticker": ticker, "price": price, "currency": prices["currency"], "previous_close": previous,
            "change": price - previous if previous else None, "change_pct": (price / previous - 1) * 100 if previous else None,
            "source": prices["source"] + " · 마지막 제공 일봉", "fetched_at": prices.get("fetched_at") or value["fetched_at"],
            "provider_time": None, "provider_date": day, "market_time": None, "status": "stale", "market_cap": None, "market_cap_currency": None}
        value["warnings"].append(f"현재 시세가 제공되지 않아 {day}의 마지막 제공 일봉 가격을 표시합니다.")
        db.execute("INSERT OR REPLACE INTO information VALUES (?,?)", (ticker, json.dumps(value, ensure_ascii=False, separators=(",", ":"))))
    db.commit(); history.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["collect", "refresh-quotes", "fill-daily-quotes", "checkpoint", "export", "publish"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.mode == "publish":
        publish(); return
    db = open_database()
    rows = charts.roster()
    if args.mode == "collect": collect(db, rows, args.limit, args.force)
    elif args.mode == "refresh-quotes": refresh_quotes(db, rows)
    elif args.mode == "fill-daily-quotes": fill_daily_quotes(db)
    elif args.mode == "checkpoint":
        history = charts.database(); checkpoint(db, rows, history); history.close()
    elif args.mode == "export": export(db)
    db.close()


if __name__ == "__main__":
    main()
