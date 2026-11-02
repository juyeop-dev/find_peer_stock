"""Prepend verified, compatible cached 2018 prices without changing later points."""
import extend_stock_history_2023 as extension


if __name__ == "__main__":
    extension.YEAR = 2018
    extension.HISTORY_START = "2017-12-20"
    extension.main()
