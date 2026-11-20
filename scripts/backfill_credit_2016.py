"""Compatibility entry point for observed 2016 KOFIA reporting dates."""
import backfill_credit as collector


def main(argv=None):
    return collector.main(argv, year=2016)


if __name__ == "__main__":
    main()
