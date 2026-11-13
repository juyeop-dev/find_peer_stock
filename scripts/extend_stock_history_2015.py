"""Prepend verified, compatible cached 2015 prices without changing later points."""
import extend_stock_history_2023 as extension


if __name__ == "__main__":
    extension.YEAR = 2015
    extension.HISTORY_START = "2014-12-20"
    extension.main()
