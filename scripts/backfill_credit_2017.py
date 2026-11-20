"""Compatibility entry point for observed 2017 KOFIA reporting dates."""
import backfill_credit as collector


def main(argv=None):
    return collector.main(argv, year=2017)


if __name__ == "__main__":
    main()
