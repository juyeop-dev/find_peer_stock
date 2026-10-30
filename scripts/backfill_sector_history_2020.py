"""Reconstruct observed 2020 sector returns before applying dated KRX amounts."""
from backfill_sector_history_2024 import main


if __name__ == "__main__":
    main(year=2020, end_before=None, audit_scope="2020")
