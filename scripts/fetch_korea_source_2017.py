"""Compatibility entry point for the approved pinned 2017 KRX source."""
import fetch_korea_source as collector


def main(argv=None):
    return collector.main(argv, year=2017)


if __name__ == "__main__":
    main()
