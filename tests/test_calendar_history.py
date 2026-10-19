from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from calendar_history import build_history, publish_history, turnover_by_currency


class CalendarHistoryTests(unittest.TestCase):
    def test_month_year_and_market_boundaries_and_empty_reports(self):
        def report(market, day, entries):
            return {"market": market, "date": day, "entries": entries}

        def stock(kind, name="회사"):
            return {"ticker": "A", "name": name, "exchange": "EX", "category": "산업", "high_type": kind}

        reports = [
            report("korea", "2026-02-02", [stock("all_time", "새 이름")]),
            report("korea", "2026-01-02", [stock("52_week")]),
            report("korea", "2026-01-05", [stock("all_time")]),
            report("korea", "2025-12-31", [stock("52_week")]),
            report("us", "2026-01-02", [stock("52_week")]),
            report("korea", "2026-03-02", []),
        ]
        history = build_history(reports, "new-highs")
        korea = next(item for item in history if item["market"] == "korea" and item["year"] == "2026")
        self.assertEqual([item["month"] for item in korea["months"]], ["2026-01", "2026-02", "2026-03"])
        january = korea["months"][0]["stocks"][0]
        self.assertEqual(january["dates"], ["2026-01-02", "2026-01-05"])
        self.assertEqual((january["high_52_week"], january["high_all_time"]), (1, 1))
        self.assertEqual(korea["months"][1]["stocks"][0]["name"], "새 이름")
        self.assertEqual(korea["months"][2]["stocks"], [])
        self.assertEqual(len(history), 3)
        with tempfile.TemporaryDirectory() as root:
            publish_history(Path(root), history)
            payload = json.loads((Path(root) / "history/korea/2026.json").read_text(encoding="utf-8"))
            self.assertEqual(payload, korea)

    def test_turnover_uses_monetary_currency_and_never_combines_currencies(self):
        def entry(currency, amount, turnover_currency=None):
            item = {"ticker": "A", "name": "회사", "exchange": "EX", "industry": "산업", "currency": currency, "turnover": amount}
            if turnover_currency:
                item["turnover_currency"] = turnover_currency
            return item

        first = entry("GBX", 100, "USD")
        second = entry("GBP", 50)
        history = build_history([
            {"market": "europe", "date": "2026-01-02", "entries": [first]},
            {"market": "europe", "date": "2026-01-05", "entries": [second]},
        ], "turnover")
        self.assertEqual(history[0]["months"][0]["stocks"][0]["turnover_by_currency"], {"USD": 100, "GBP": 50})
        self.assertEqual(turnover_by_currency([first, second]), {"GBP": 50, "USD": 100})
        self.assertEqual(turnover_by_currency([]), {})


if __name__ == "__main__":
    unittest.main()
