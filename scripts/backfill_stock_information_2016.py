"""Recover reported 2016 financials while preserving all later periods."""
import backfill_stock_information_2024_h2 as recovery


def configure():
    return recovery.financial_request(year=2016, root=recovery.info.ROOT)


if __name__ == "__main__":
    recovery.main(request=configure())
