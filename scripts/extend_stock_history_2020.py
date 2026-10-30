"""Prepend verified, compatible cached 2020 prices without changing later points."""
import extend_stock_history_2023 as extension


if __name__ == "__main__":
    extension.YEAR = 2020
    extension.HISTORY_START = "2019-12-20"
    extension.main()
