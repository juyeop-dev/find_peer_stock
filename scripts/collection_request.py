"""Shared collection context; dates here are requests, never publication proof."""
from dataclasses import dataclass
from pathlib import Path
from history_policy import DEFAULT_POLICY
from price_history_range import load_price_range

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CollectionRequest:
    start: str
    end: str
    as_of: str
    scope: str
    key: str
    state: Path
    audit: Path
    reference_start: str


def collection_request(*, year=None, config=DEFAULT_POLICY, root=ROOT, as_of=None, through_present=False):
    value = load_price_range(config, year=year, as_of=as_of, through_present=through_present)
    key = (str(value.year) if year is not None else
           f"{value.year}_onward" if value.end_year is None else
           str(value.year) if value.year == value.end_year else f"{value.year}_{value.end_year}")
    return CollectionRequest(value.start, value.end, value.as_of, key, key,
                             Path(root) / f"data/tmp_{key}",
                             Path(root) / "data/information-audit" / key, value.reference_start)
