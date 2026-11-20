"""Compatibility entry point for observed 2014 KOFIA reporting dates."""
import backfill_credit as collector


def main(argv=None):
    return collector.main(argv, year=2014)


if __name__ == "__main__":
    main()
