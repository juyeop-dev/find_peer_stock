"""Explicit price collection ranges; requested dates are not published coverage."""
from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path

from history_policy import DEFAULT_POLICY, resolve_history_policy


@dataclass(frozen=True)
class PriceHistoryRange:
    start: str
    end: str
    reference_start: str
    as_of: str
    end_year: int | None
    reference_days: int

    @property
    def year(self):
        return int(self.start[:4])

    @property
    def scope(self):
        # Retain existing state tables for the original ongoing price refresh.
        # Bounded requests and changed reference windows get independent state.
        if self.end_year is None and self.reference_days == 12:
            return str(self.year)
        identity = [self.start, self.end_year, self.reference_days]
        digest = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:16]
        return f"{self.year}_{digest}"

    @property
    def table(self):
        return f"history_{self.scope}_updates"

    def storage_start(self):
        # Keep the existing minimum two-year window, relative to the requested
        # endpoint, even when the policy starts more recently.
        try:
            recent = date.fromisoformat(self.end) - timedelta(days=732)
        except OverflowError:
            recent = date.min
        return min(self.reference_start, recent.isoformat())

    def bound(self, value):
        cutoff = self.storage_start()
        prices = [point for point in value["prices"]
                  if cutoff <= point[0] <= self.end]
        if len(prices) < 2:
            raise ValueError("Fewer than two valid original daily prices in requested range")
        return {**value, "prices": prices}


def load_price_range(path=DEFAULT_POLICY, *, as_of=None, year=None, through_present=False):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    # Validate the entire input even when a compatibility wrapper selects a
    # specific year. Only its year overrides the collection years, never the
    # policy's reference window or validation rules.
    validated = resolve_history_policy(value, as_of=as_of)
    if year is not None:
        value = {**value, "collection": {**value["collection"],
                 "start_year": year, "end_year": None if through_present else year}}
    resolved = resolve_history_policy(value, as_of=validated["as_of"]) if year is not None else validated
    collection = resolved["collection"]
    return PriceHistoryRange(collection["start_date"], collection["end_date"],
                             collection["price_reference_start"], resolved["as_of"],
                             None if value["collection"]["end_year"] is None else collection["end_year"],
                             collection["price_reference_days"])
