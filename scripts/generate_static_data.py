from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = PROJECT_ROOT / "data" / "seed" / "peer_alerts"
GENERATED_DIR = PROJECT_ROOT / "data" / "generated"
FRONTEND_DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"
KST = ZoneInfo("Asia/Seoul")
MARKET_SCHEDULES = {
    "한국": {
        "market": "KRX",
        "timezone": "Asia/Seoul",
        "sessions": ((time(9, 0), time(15, 30)),),
    },
    "일본": {
        "market": "TSE",
        "timezone": "Asia/Tokyo",
        "sessions": ((time(9, 0), time(11, 30)), (time(12, 30), time(15, 30))),
    },
    "대만": {
        "market": "TWSE",
        "timezone": "Asia/Taipei",
        "sessions": ((time(9, 0), time(13, 30)),),
    },
    "홍콩": {
        "market": "HKEX",
        "timezone": "Asia/Hong_Kong",
        "sessions": ((time(9, 30), time(12, 0)), (time(13, 0), time(16, 0))),
    },
    "중국": {
        "market": "SSE/SZSE",
        "timezone": "Asia/Shanghai",
        "sessions": ((time(9, 30), time(11, 30)), (time(13, 0), time(15, 0))),
    },
    "미국": {
        "market": "NYSE/Nasdaq",
        "timezone": "America/New_York",
        "sessions": ((time(9, 30), time(16, 0)),),
    },
}

QUOTE_SOURCE_DIR = PROJECT_ROOT / "scripts" / "quote_sources"
sys.path.insert(0, str(QUOTE_SOURCE_DIR))

try:
    from korea_quote import fetch_korean_quote, is_korean_ticker
    from taiwan_quote import fetch_taiwan_quote, is_taiwan_ticker
    from yahoo_chart import MarketDataError, Quote, fetch_latest_quote
except ImportError as exc:  # pragma: no cover - handled at runtime for friendly CLI errors
    fetch_korean_quote = None
    is_korean_ticker = None
    fetch_taiwan_quote = None
    is_taiwan_ticker = None
    fetch_latest_quote = None

    class MarketDataError(RuntimeError):
        pass

    class Quote:  # type: ignore[no-redef]
        pass

    QUOTE_IMPORT_ERROR: Exception | None = exc
else:
    QUOTE_IMPORT_ERROR = None


@dataclass(frozen=True)
class MarketState:
    country: str
    market: str
    timezone: str
    is_open: bool
    local_time: datetime
    reason: str
    session_label: str


def main() -> None:
    args = parse_args()
    generated_at = parse_now(args.now) if args.now else datetime.now(tz=KST)
    seed_configs = load_seed_configs(args.seed_dir)
    catalog = build_catalog(seed_configs)
    previous_quotes = load_previous_quotes(args.output_dir, args.frontend_data_dir)

    quotes = {}
    for ticker in sorted(catalog["companies"]):
        quotes[ticker] = build_quote_snapshot(
            ticker,
            generated_at=generated_at,
            no_fetch=args.no_fetch,
            force_fetch=args.force_fetch,
            previous_quote=previous_quotes.get(ticker),
        )

    if args.skip_write_when_no_fetch and should_skip_write(quotes):
        print("No market-open fetches were needed; kept existing static data unchanged.")
        return

    write_static_data(catalog, quotes, generated_at=generated_at, output_dir=args.output_dir)

    if args.copy_to_frontend:
        sync_frontend_data(args.output_dir, args.frontend_data_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate static JSON data for the stock peer site.")
    parser.add_argument("--seed-dir", type=Path, default=SEED_DIR)
    parser.add_argument("--output-dir", type=Path, default=GENERATED_DIR)
    parser.add_argument("--frontend-data-dir", type=Path, default=FRONTEND_DATA_DIR)
    parser.add_argument("--no-fetch", action="store_true", help="Generate JSON without calling quote sources.")
    parser.add_argument("--force-fetch", action="store_true", help="Fetch every ticker, ignoring market hours.")
    parser.add_argument("--now", help="Override current time for testing. Example: 2026-05-14T10:00:00+09:00")
    parser.add_argument(
        "--skip-write-when-no-fetch",
        action="store_true",
        help="Do not rewrite JSON if all quotes were reused because markets are closed.",
    )
    parser.add_argument(
        "--copy-to-frontend",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Copy generated data into frontend/public/data.",
    )
    return parser.parse_args()


def load_seed_configs(seed_dir: Path) -> list[dict[str, Any]]:
    if not seed_dir.exists():
        raise SystemExit(f"Seed directory not found: {seed_dir}")

    configs = []
    for path in sorted(seed_dir.glob("*.json")):
        configs.append(json.loads(path.read_text(encoding="utf-8")))

    if not configs:
        raise SystemExit(f"No seed JSON files found in: {seed_dir}")

    return configs


def build_catalog(seed_configs: list[dict[str, Any]]) -> dict[str, Any]:
    companies: dict[str, dict[str, Any]] = {}
    target_tickers: list[str] = []
    target_pages: dict[str, dict[str, Any]] = {}
    reverse_links: dict[str, list[str]] = {}

    for config in seed_configs:
        target = config.get("target") or {}
        target_ticker = str(target.get("ticker") or "").strip()
        if not target_ticker:
            continue

        target_profile = normalize_company(
            {
                **target,
                "id": config.get("id"),
                "title": config.get("title"),
                "market_note": config.get("market_note"),
                "country": target.get("country") or infer_country(target_ticker),
                "is_target": True,
            }
        )
        merge_company(companies, target_profile)
        target_tickers.append(target_ticker)

        page_groups = []
        for group in config.get("peer_groups") or []:
            if group.get("active") is False:
                continue

            peers = []
            for peer in group.get("peers") or []:
                if peer.get("active") is False:
                    continue

                peer_profile = normalize_company(
                    {
                        **peer,
                        "country": peer.get("country") or infer_country(peer.get("ticker")),
                        "is_target": False,
                    }
                )
                peer_ticker = peer_profile["ticker"]
                merge_company(companies, peer_profile)
                peers.append(peer_ticker)
                reverse_links.setdefault(peer_ticker, []).append(target_ticker)

            if peers:
                page_groups.append(
                    {
                        "group": {
                            "emoji": group.get("emoji"),
                            "name": group.get("name"),
                            "summary": group.get("summary"),
                        },
                        "peers": peers,
                    }
                )

        target_pages[target_ticker] = {"peer_groups": page_groups}

    add_reverse_peer_groups(target_pages, reverse_links)

    return {
        "companies": companies,
        "target_tickers": unique(target_tickers),
        "target_pages": target_pages,
    }


def add_reverse_peer_groups(target_pages: dict[str, dict[str, Any]], reverse_links: dict[str, list[str]]) -> None:
    for peer_ticker, linked_target_tickers in reverse_links.items():
        page = target_pages.setdefault(peer_ticker, {"peer_groups": []})
        existing_tickers = set(flatten_group_tickers(page["peer_groups"]))
        reverse_peers = [
            ticker
            for ticker in unique(linked_target_tickers)
            if ticker != peer_ticker and ticker not in existing_tickers
        ]
        if not reverse_peers:
            continue

        page["peer_groups"].append(
            {
                "group": {
                    "emoji": "↔",
                    "name": "연결된 대상 종목",
                    "summary": "이 종목을 peer로 보는 종목",
                },
                "peers": reverse_peers,
            }
        )


def normalize_company(raw: dict[str, Any]) -> dict[str, Any]:
    ticker = str(raw.get("ticker") or "").strip()
    if not ticker:
        raise ValueError(f"Company ticker missing: {raw}")

    name_kr = raw.get("name_kr") or raw.get("name_en") or ticker
    name_en = raw.get("name_en") or raw.get("name_kr") or ticker

    return {
        "id": raw.get("id") or ticker_to_id(ticker),
        "name_kr": name_kr,
        "name_en": name_en,
        "ticker": ticker,
        "country": raw.get("country") or infer_country(ticker),
        "theme": raw.get("theme") or raw.get("sector") or raw.get("note") or "",
        "market_note": raw.get("market_note") or "",
        "sector": raw.get("sector") or "",
        "note": raw.get("note") or "",
        "title": raw.get("title") or "",
        "is_target": bool(raw.get("is_target")),
    }


def merge_company(companies: dict[str, dict[str, Any]], incoming: dict[str, Any]) -> None:
    ticker = incoming["ticker"]
    current = companies.get(ticker)
    if current is None:
        companies[ticker] = incoming
        return

    merged = {**current}
    for key, value in incoming.items():
        if value and not merged.get(key):
            merged[key] = value
    merged["is_target"] = bool(current.get("is_target") or incoming.get("is_target"))
    companies[ticker] = merged


def load_previous_quotes(output_dir: Path, frontend_data_dir: Path) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    for data_dir in (frontend_data_dir, output_dir):
        stocks_dir = data_dir / "stocks"
        if not stocks_dir.exists():
            continue

        for path in sorted(stocks_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            quote = payload.get("quote")
            ticker = quote.get("ticker") if isinstance(quote, dict) else None
            if ticker and ticker not in quotes:
                quotes[ticker] = quote

    return quotes


def should_skip_write(quotes: dict[str, dict[str, Any]]) -> bool:
    if not quotes:
        return False

    refresh_statuses = {quote.get("refresh_status") for quote in quotes.values()}
    attempted_fetch_statuses = {"fetched", "error"}
    missing_previous_statuses = {"market_closed_no_previous", "not_fetched"}
    return not (refresh_statuses & attempted_fetch_statuses) and not (refresh_statuses & missing_previous_statuses)


def build_quote_snapshot(
    ticker: str,
    *,
    generated_at: datetime,
    no_fetch: bool,
    force_fetch: bool,
    previous_quote: dict[str, Any] | None,
) -> dict[str, Any]:
    market_state = get_market_state(ticker, generated_at)

    if no_fetch:
        return empty_quote(ticker, generated_at, "not fetched", market_state, refresh_status="not_fetched")

    if not force_fetch and not market_state.is_open:
        if previous_quote:
            return reuse_previous_quote(previous_quote, generated_at, market_state)
        return empty_quote(
            ticker,
            generated_at,
            f"market closed; no previous quote available ({market_state.reason})",
            market_state,
            refresh_status="market_closed_no_previous",
        )

    if QUOTE_IMPORT_ERROR is not None:
        return empty_quote(
            ticker,
            generated_at,
            f"quote source import failed: {QUOTE_IMPORT_ERROR}",
            market_state,
            refresh_status="error",
        )

    try:
        quote = fetch_quote(ticker)
    except Exception as exc:
        return empty_quote(ticker, generated_at, str(exc), market_state, refresh_status="error")

    return quote_to_dict(quote, fetched_at=generated_at, source=infer_source(ticker), market_state=market_state)


def fetch_quote(ticker: str) -> Quote:
    if is_korean_ticker and is_korean_ticker(ticker):
        return fetch_korean_quote(ticker)

    if is_taiwan_ticker and is_taiwan_ticker(ticker):
        try:
            return fetch_taiwan_quote(ticker)
        except MarketDataError:
            return fetch_latest_quote(ticker)

    include_prepost = ticker.upper() in {"FCX", "MU", "SCCO", "SNDK"}
    return fetch_latest_quote(ticker, include_prepost=include_prepost)


def quote_to_dict(quote: Quote, *, fetched_at: datetime, source: str, market_state: MarketState) -> dict[str, Any]:
    return {
        "ticker": quote.ticker,
        "price": quote.price,
        "previous_close": quote.previous_close,
        "change": quote.change,
        "change_pct": quote.change_pct,
        "currency": quote.currency,
        "source": source,
        "fetched_at": fetched_at.isoformat(),
        "market_time": quote.timestamp.isoformat() if quote.timestamp else None,
        "basis_label": quote.basis_label,
        "status": "ok",
        "error": None,
        **market_state_fields(market_state, refresh_status="fetched"),
    }


def reuse_previous_quote(
    previous_quote: dict[str, Any],
    generated_at: datetime,
    market_state: MarketState,
) -> dict[str, Any]:
    reused = {**previous_quote}
    reused.update(market_state_fields(market_state, refresh_status="market_closed_reused"))
    reused["last_checked_at"] = generated_at.isoformat()
    return reused


def empty_quote(
    ticker: str,
    fetched_at: datetime,
    error: str,
    market_state: MarketState,
    *,
    refresh_status: str,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "price": None,
        "previous_close": None,
        "change": None,
        "change_pct": None,
        "currency": infer_currency(ticker),
        "source": infer_source(ticker),
        "fetched_at": fetched_at.isoformat(),
        "market_time": None,
        "basis_label": None,
        "status": "error",
        "error": error,
        **market_state_fields(market_state, refresh_status=refresh_status),
    }


def market_state_fields(market_state: MarketState, *, refresh_status: str) -> dict[str, Any]:
    return {
        "market": market_state.market,
        "market_country": market_state.country,
        "market_timezone": market_state.timezone,
        "market_status": "open" if market_state.is_open else "closed",
        "market_status_reason": market_state.reason,
        "market_session": market_state.session_label,
        "refresh_status": refresh_status,
    }


def write_static_data(
    catalog: dict[str, Any],
    quotes: dict[str, dict[str, Any]],
    *,
    generated_at: datetime,
    output_dir: Path,
) -> None:
    stocks_dir = output_dir / "stocks"
    stocks_dir.mkdir(parents=True, exist_ok=True)

    companies = catalog["companies"]
    stock_index = []
    for ticker, company in sorted(companies.items(), key=lambda item: (not item[1].get("is_target"), item[0])):
        stock_index.append(
            {
                "id": company["id"],
                "ticker": ticker,
                "name_kr": company["name_kr"],
                "name_en": company["name_en"],
                "country": company["country"],
                "theme": company["theme"],
                "is_target": company["is_target"],
                "summary_path": stock_summary_path(ticker),
            }
        )

    write_json(
        output_dir / "index.json",
        {
            "generated_at": generated_at.isoformat(),
            "stocks": stock_index,
            "featured_tickers": catalog["target_tickers"],
            "market_indices": [],
        },
    )

    for ticker, company in companies.items():
        page = catalog["target_pages"].get(ticker, {"peer_groups": []})
        peer_groups = []
        for group in page["peer_groups"]:
            peer_groups.append(
                {
                    "group": group["group"],
                    "peers": [
                        {
                            "company": companies[peer_ticker],
                            "quote": quotes[peer_ticker],
                            "summary_path": stock_summary_path(peer_ticker),
                        }
                        for peer_ticker in group["peers"]
                    ],
                }
            )

        sources = sorted({quotes[t]["source"] for t in [ticker, *flatten_group_tickers(page["peer_groups"])]})
        write_json(
            stocks_dir / f"{ticker}.json",
            {
                "generated_at": generated_at.isoformat(),
                "company": company,
                "quote": quotes[ticker],
                "peer_groups": peer_groups,
                "sources": sources,
            },
        )


def sync_frontend_data(output_dir: Path, frontend_data_dir: Path) -> None:
    if frontend_data_dir.exists():
        shutil.rmtree(frontend_data_dir)
    shutil.copytree(output_dir, frontend_data_dir)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def flatten_group_tickers(groups: list[dict[str, Any]]) -> list[str]:
    tickers = []
    for group in groups:
        tickers.extend(group["peers"])
    return tickers


def get_market_state(ticker: str, current_time: datetime) -> MarketState:
    country = infer_country(ticker)
    schedule = MARKET_SCHEDULES.get(country)
    if schedule is None:
        local_time = current_time.astimezone(KST)
        return MarketState(
            country=country,
            market="Unknown",
            timezone="Asia/Seoul",
            is_open=False,
            local_time=local_time,
            reason="market schedule not configured",
            session_label="-",
        )

    timezone = str(schedule["timezone"])
    local_time = current_time.astimezone(ZoneInfo(timezone))
    sessions = schedule["sessions"]
    session_label = format_sessions(sessions)

    if local_time.weekday() >= 5:
        return MarketState(
            country=country,
            market=str(schedule["market"]),
            timezone=timezone,
            is_open=False,
            local_time=local_time,
            reason=f"weekend in {timezone}",
            session_label=session_label,
        )

    local_clock = local_time.time()
    is_open = any(start <= local_clock < end for start, end in sessions)
    return MarketState(
        country=country,
        market=str(schedule["market"]),
        timezone=timezone,
        is_open=is_open,
        local_time=local_time,
        reason="regular session open" if is_open else f"outside regular session in {timezone}",
        session_label=session_label,
    )


def format_sessions(sessions: tuple[tuple[time, time], ...]) -> str:
    return ", ".join(f"{start:%H:%M}-{end:%H:%M}" for start, end in sessions)


def parse_now(raw_value: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw_value)
    except ValueError as exc:
        raise SystemExit("--now must be ISO 8601, for example 2026-05-14T10:00:00+09:00") from exc

    if value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value


def stock_summary_path(ticker: str) -> str:
    return f"data/stocks/{ticker}.json"


def ticker_to_id(ticker: str) -> str:
    return ticker.lower().replace(".", "_").replace("-", "_")


def infer_country(ticker: str | None) -> str:
    if not ticker:
        return "-"
    upper = ticker.upper()
    if upper.endswith(".KS") or upper.endswith(".KQ"):
        return "한국"
    if upper.endswith(".T"):
        return "일본"
    if upper.endswith(".TW"):
        return "대만"
    if upper.endswith(".HK"):
        return "홍콩"
    if upper.endswith(".SS") or upper.endswith(".SZ"):
        return "중국"
    return "미국"


def infer_currency(ticker: str) -> str:
    country = infer_country(ticker)
    return {
        "한국": "KRW",
        "일본": "JPY",
        "대만": "TWD",
        "홍콩": "HKD",
        "중국": "CNY",
    }.get(country, "USD")


def infer_source(ticker: str) -> str:
    country = infer_country(ticker)
    if country == "한국":
        return "Naver Finance / TradingView"
    if country == "대만":
        return "TWSE / Yahoo Finance"
    return "Yahoo Finance"


def unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


if __name__ == "__main__":
    main()
