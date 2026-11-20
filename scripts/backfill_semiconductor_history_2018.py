"""Compatibility entry point for verified 2018 semiconductor history."""
import backfill_semiconductor_history as collector


def fetch(stock):
    request = collector.collection_request(year=2018, root=collector.semi.ROOT, through_present=True)
    return collector.fetch(stock, request)


def main(argv=None):
    return collector.main(argv, year=2018)


if __name__ == "__main__":
    main()
