"""Reconstruct dated sector returns from verified Naver daily bars.

Membership uses the explicitly dated current classification, not a fictitious
historical constituent list. Historical capitalization is deliberately null.
"""
import bisect
import calendar
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path

from backfill_korean_new_highs import history_url, parse_history
from stock_chart_history import ROOT, write_json


def previous_month(day, months):
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def reconstruct(stock, history, day):
    current = history.get(day)
    if not current or current[4] <= 0 or current[5] <= 0:
        return None
    dates = sorted(d for d, row in history.items() if row[4] > 0)
    index = bisect.bisect_left(dates, day)
    targets = {"day": dates[index - 1] if index else None, "week": day - timedelta(days=7),
               "month": previous_month(day, 1), "quarter": previous_month(day, 3), "year": previous_month(day, 12)}
    returns = {}
    for key, target in targets.items():
        anchor = bisect.bisect_right(dates, target) - 1 if target else -1
        returns[key] = (current[4] / history[dates[anchor]][4] - 1) * 100 if anchor >= 0 else None
    return {**stock, "date": day.isoformat(), "price": current[4], "change_pct": returns["day"],
            "returns": returns, "turnover": current[4] * current[5], "market_cap": None}


def main():
    directory = ROOT / "data/sectors"
    latest = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    sessions = sorted(date.fromisoformat(p.stem) for p in (ROOT / "data/new-highs/reports/korea").glob("2024-*.json"))
    if not sessions:
        raise ValueError("Verified Korean calendar reports must be collected first")
    earliest, last = sessions[0] - timedelta(weeks=52), sessions[-1]
    histories, missing = {}, []
    for stock in latest["stocks"]:
        code = stock["code"]
        url = history_url(code, earliest, last)
        path = ROOT / "data/tmp_korean_history" / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        if not path.exists():
            missing.append(stock["ticker"])
            continue
        histories[stock["ticker"]] = parse_history(json.loads(path.read_text(encoding="utf-8")), code=code, start=earliest, end=last)
    if len(histories) < len(latest["stocks"]) * .95:
        raise ValueError(f"Incomplete sector source coverage: {len(histories)}/{len(latest['stocks'])}")
    fetched_at = datetime.now(timezone.utc).isoformat()
    for day in sessions:
        path = directory / "daily" / f"{day}.json.gz"
        if path.exists():
            continue
        stocks = [value for stock in latest["stocks"] if (value := reconstruct(stock, histories.get(stock["ticker"], {}), day))]
        if len(stocks) < len(histories) * .75:
            raise ValueError(f"Incomplete historical session: {day} {len(stocks)}/{len(histories)}")
        snapshot = {"schema_version": 1, "market": "korea", "currency": "KRW", "date": day.isoformat(),
            "fetched_at": fetched_at, "source": "Naver Finance historical daily bars · TradingView current classification",
            "source_url": "https://stock.naver.com/", "universe": "현재 KOSPI·KOSDAQ 보통주 분류에서 당시 거래가 확인된 종목 · 상장폐지 종목 제외",
            "received": len(latest["stocks"]), "excluded": {"no_history": len(missing), "no_session": len(histories) - len(stocks)},
            "stale_count": 0, "stocks": stocks,
            "reconstruction": {"classification_date": latest["date"], "classification_source": latest["source_url"],
                "note": "현재 업종 분류 기준으로 과거 주가를 재구성한 자료입니다. 당시 구성 종목 전체와 다를 수 있습니다. 거래대금은 종가×거래량 추정치이며 당시 시가총액은 제공하지 않습니다.",
                "returns": "Adjusted close at session / last adjusted close on or before calendar lookback date - 1; daily uses previous observed session"}}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".gz.tmp")
        temporary.write_bytes(gzip.compress(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(), mtime=0))
        temporary.replace(path)
    write_json(ROOT / "data/information-audit/2024-h2/sector-progress.json", {"sessions": len(sessions), "start": sessions[0].isoformat(), "end": sessions[-1].isoformat(),
        "classification_date": latest["date"], "source_coverage": len(histories), "missing": missing})
    print(f"Reconstructed {len(sessions)} sector sessions, {len(histories)} verified histories, classification {latest['date']}")


if __name__ == "__main__":
    main()
