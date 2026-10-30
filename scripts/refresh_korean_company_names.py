"""Refresh verified Korean listing names without changing historical prices."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "data/seed/korean_company_names.json"


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as response:
        return json.load(response)


def listing_names(board):
    names = {}
    for page in range(1, 101):
        payload = fetch(f"https://m.stock.naver.com/api/stocks/marketValue/{board}?page={page}&pageSize=100")
        if payload.get("stockListCategoryType") != board or not isinstance(payload.get("stocks"), list):
            raise ValueError(f"Invalid listing response for {board}")
        for stock in payload["stocks"]:
            code, name = stock.get("itemCode", ""), stock.get("stockName", "").strip()
            exchange = stock.get("stockExchangeType") or {}
            if len(code) != 6 or not code.isalnum() or not name or exchange.get("name") != board:
                raise ValueError(f"Invalid listing identity: {code}")
            ticker = f"{code}.{'KS' if board == 'KOSPI' else 'KQ'}"
            if ticker in names:
                raise ValueError(f"Duplicate listing: {ticker}")
            names[ticker] = name
        if len(payload["stocks"]) < 100:
            return names
    raise ValueError(f"Incomplete listing pagination: {board}")


def main():
    with ThreadPoolExecutor(max_workers=2) as pool:
        boards = list(pool.map(listing_names, ["KOSPI", "KOSDAQ"]))
    names = {key: name for board in boards for key, name in board.items()}
    if len(names) < 2500:
        raise ValueError("Incomplete Korean listing universe")
    previous = json.loads(TARGET.read_text(encoding="utf-8")) if TARGET.exists() else {}
    value = {"verified_at": datetime.now(timezone.utc).isoformat(),
             "source": "Naver Finance Korean listing names",
             "source_url": "https://m.stock.naver.com/api/stocks/marketValue/",
             "names": dict(sorted({**previous.get("names", {}), **names}.items()))}
    temporary = TARGET.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(TARGET)
    print(f"Verified {len(names)} Korean listing names")


if __name__ == "__main__":
    main()
