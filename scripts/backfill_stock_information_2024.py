"""Recover the entire 2024 financial year using an independent resumable state."""
import backfill_stock_information_2024_h2 as recovery


def configure():
    return recovery.financial_request(year=2024, root=recovery.info.ROOT)


if __name__ == "__main__":
    recovery.main(request=configure())
