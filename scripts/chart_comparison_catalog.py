"""Add retained company classifications to the searchable chart catalog."""
import json
import math


def enrich_chart_catalog(entries, information, root):
    classifications, peers, identities = {}, {}, {}
    path = root / "data/seed/semiconductor_categories.json"
    if path.exists():
        for group in json.loads(path.read_text(encoding="utf-8")):
            key = "/".join(group[field] for field in ("major", "middle", "minor"))
            for ticker in group.get("image", []) + group.get("additional", []):
                classifications.setdefault(ticker, set()).add(key)
    for path in sorted((root / "data/generated/stocks").glob("*.json")):
        summary = json.loads(path.read_text(encoding="utf-8"))
        company = summary.get("company") or {}
        ticker = company.get("ticker")
        if not ticker:
            continue
        identities[ticker] = company.get("id")
        for group in summary.get("peer_groups", []):
            group_name = (group.get("group") or {}).get("name")
            business = f"피어 사업/{group_name}" if group_name and group_name != "연결된 대상 종목" else None
            for peer in group.get("peers", []):
                other = peer.get("company") or {}
                if other.get("ticker") and other["ticker"] != ticker:
                    peers.setdefault(ticker, set()).add(other["ticker"])
                    identities[other["ticker"]] = other.get("id")
                    if business:
                        classifications.setdefault(ticker, set()).add(business)
                        classifications.setdefault(other["ticker"], set()).add(business)
    for entry in entries:
        ticker = entry["ticker"]
        value = information.get(ticker) or {}
        company, quote = value.get("company") or {}, value.get("quote") or {}
        for field in ("sector", "industry"):
            if isinstance(company.get(field), str) and company[field].strip():
                entry[field] = company[field].strip()
        if classifications.get(ticker):
            entry["business_groups"] = sorted(classifications[ticker])
        if peers.get(ticker):
            entry["peer_tickers"] = sorted(peers[ticker])
        if identities.get(ticker):
            entry["company_id"] = identities[ticker]
        cap = quote.get("market_cap_usd")
        if type(cap) in (int, float) and math.isfinite(cap) and cap > 0:
            entry["market_cap_usd"] = cap
    return entries
