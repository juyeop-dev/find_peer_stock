"""Compatibility entry point for 2018 replay originals."""
import backfill_chart_replay as collector


def main(argv=None):
    return collector.main(argv, year=2018)


if __name__ == "__main__":
    main()
