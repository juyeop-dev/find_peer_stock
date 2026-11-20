"""Compatibility entry point for 2014 replay originals."""
import backfill_chart_replay as collector


def main(argv=None):
    return collector.main(argv, year=2014)


if __name__ == "__main__":
    main()
