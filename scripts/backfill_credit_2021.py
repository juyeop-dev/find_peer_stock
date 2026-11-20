"""Compatibility entry point for observed 2021 KOFIA reporting dates."""
import backfill_credit as collector


def main(argv=None):
    return collector.main(argv, year=2021)


if __name__ == "__main__":
    main()
