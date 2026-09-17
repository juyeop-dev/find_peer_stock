from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from turnover_sources import tradingview as source  # noqa: E402


DAY = date(2026, 9, 17)
STAMP = int(datetime(2026, 9, 17, 6, tzinfo=timezone.utc).timestamp())


def row(symbol: str, turnover: int, **overrides: object) -> dict:
    exchange, code = symbol.split(":", 1)
    values = {"name": code, "description": f"Company {code}", "exchange": exchange, "type": "stock",
              "subtype": "common", "sector": "Technology", "industry": "Semiconductors", "close": 100,
              "change": 1.25, "Value.Traded": turnover, "market_cap_basic": 1_000_000, "currency": "JPY",
              "time": STAMP, "indexes": [], "logoid": "sample-logo"}
    values.update(overrides)
    return {"s": symbol, "d": [values[column] for column in source.COLUMNS]}


class TradingViewTurnoverTests(unittest.TestCase):
    def test_ranks_top_30_and_maps_fields(self) -> None:
        rows = [row(f"TSE:{1000 + index}", index + 1) for index in range(35)]
        with patch.object(source, "_request_json", return_value={"totalCount": 35, "data": rows}):
            report = source.fetch_report("japan", DAY)
        self.assertEqual(len(report["entries"]), 30)
        self.assertEqual(report["entries"][0]["ticker"], "1034.T")
        self.assertEqual(report["entries"][0]["rank"], 1)
        self.assertEqual(report["entries"][0]["turnover"], 35)
        self.assertEqual(report["entries"][-1]["rank"], 30)
        self.assertEqual(report["entries"][0]["logo_url"], "https://s3-symbol-logo.tradingview.com/sample-logo--big.svg")

    def test_rejects_stale_session(self) -> None:
        stale = row("TSE:1000", 100)
        stale["d"][source.COLUMNS.index("time")] = STAMP - 86400
        with patch.object(source, "_request_json", return_value={"totalCount": 1, "data": [stale]}):
            with self.assertRaises(source.TurnoverSourceNotReady):
                source.fetch_report("japan", DAY)


if __name__ == "__main__":
    unittest.main()
