"""Reconstruct 2023 sectors from observed prices before applying dated KRX metrics."""
from backfill_sector_history_2024 import main


if __name__ == "__main__":
    main(year=2023, end_before=None, audit_scope="2023")
