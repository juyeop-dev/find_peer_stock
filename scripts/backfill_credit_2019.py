"""Compatibility entry point for observed 2019 KOFIA reporting dates."""
import backfill_credit as collector


def main(argv=None):
    return collector.main(argv, year=2019)


if __name__ == "__main__":
    main()
