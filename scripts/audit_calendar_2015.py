"""Validate every 2015 calendar session and domestic reference series."""
from audit_calendar_2023 import main

if __name__ == "__main__":
    # The retained current-company cohort contains 1,465 stocks in January
    # 2015. Validate its matched fraction instead of a 2016 cohort-size floor.
    main(year=2015, minimum_sector_matches=1400, minimum_sector_match_ratio=.95)
