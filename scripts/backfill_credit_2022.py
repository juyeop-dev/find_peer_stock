"""Compatibility entry point for observed 2022 KOFIA reporting dates."""
import backfill_credit as collector


def main(argv=None):
    return collector.main(argv, year=2022)


if __name__ == "__main__":
    main()
