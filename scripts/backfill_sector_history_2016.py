"""Reconstruct observed 2016 sector returns before applying dated KRX amounts."""
from backfill_sector_history_2024 import main


if __name__ == "__main__":
    main(year=2016, end_before=None, audit_scope="2016")
