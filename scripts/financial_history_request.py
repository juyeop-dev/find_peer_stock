"""Validated financial collection/audit context, independent of module globals."""
from dataclasses import dataclass
from pathlib import Path

from history_policy import DEFAULT_POLICY
from price_history_range import load_price_range

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class FinancialRequest:
    start: str
    end: str
    as_of: str
    scope: str
    state: Path
    audit: Path
    table: str
    coverage_key: str
    fetched_key: str
    resume: str
    covered_status: str
    periods_key: str


def financial_request(*, year=None, half=None, config=DEFAULT_POLICY, root=ROOT, as_of=None):
    resolved = load_price_range(config, year=year, as_of=as_of)
    start, end = resolved.start, resolved.end
    if half is not None:
        if half != 2 or year is None:
            raise ValueError("Only an explicit year's second half is supported")
        start = f"{resolved.year:04d}-07-01"
        if start > end:
            raise ValueError("Financial range must not start after its endpoint")
    if half:
        scope, key = f"{resolved.year}-h2", f"{resolved.year}_h2"
    elif year is not None:
        scope = key = str(resolved.year)
    else:
        scope = key = (f"{resolved.year}_onward" if resolved.end_year is None else
                       str(resolved.year) if resolved.year == resolved.end_year else
                       f"{resolved.year}_{resolved.end_year}")
    legacy = year is not None and 2014 <= resolved.year <= 2024
    script = f"backfill_stock_information_{key}.py" if legacy else "backfill_stock_information.py"
    resume = f"python -u scripts/{script} collect"
    if year is not None and not legacy:
        resume += f" --year {resolved.year}"
    return FinancialRequest(start, end, resolved.as_of, scope,
                            Path(root) / f"data/tmp_{key}",
                            Path(root) / "data/information-audit" / scope,
                            f"financial_{key}_updates", f"historical_{key}_coverage",
                            f"historical_{key}_fetched_at", resume,
                            f"covers_h2_{year}" if half else f"covers_{key}",
                            "h2_financial_periods" if half else f"financial_{key}_periods")
