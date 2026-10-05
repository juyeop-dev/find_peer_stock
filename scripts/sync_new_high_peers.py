"""Copy the shared company peer mapping into this standalone site repository."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = SITE_ROOT.parent / "company_info" / "peer_map.json"
DEFAULT_OUTPUT = SITE_ROOT / "data" / "new-highs" / "peer-map.json"


def sync(source: Path = DEFAULT_SOURCE, output: Path = DEFAULT_OUTPUT) -> int:
    peer_map = json.loads(source.read_text(encoding="utf-8-sig"))
    result: dict[str, list[dict[str, str]]] = {}
    for ticker, row in sorted(peer_map.items()):
        codes = row.get("peer_tickers") or []
        labels = row.get("peer_labels") or []
        if len(labels) != len(codes):
            raise ValueError(f"{ticker}: peer labels and tickers differ in length")
        if codes:
            result[ticker] = [
                {"ticker": code, "name": label.rsplit("(", 1)[0].strip()}
                for code, label in zip(codes, labels)
            ]
            if any(not peer["name"] for peer in result[ticker]):
                raise ValueError(f"{ticker}: empty peer name")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"schema_version": 1, "peers_by_ticker": result},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(f"Synced peers for {sync(args.source, args.output)} stocks.")
