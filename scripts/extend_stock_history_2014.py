"""Prepend verified, compatible cached 2014 prices without changing later points."""
import extend_stock_history_2023 as extension


if __name__ == "__main__":
    extension.YEAR = 2014
    extension.HISTORY_START = "2013-12-20"
    extension.CACHE_YEARS = [2014]
    extension.main()
