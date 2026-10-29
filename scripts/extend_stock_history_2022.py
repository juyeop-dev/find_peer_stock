"""Prepend verified, compatible cached 2022 prices without changing later points."""
import extend_stock_history_2023 as extension


if __name__ == "__main__":
    extension.YEAR = 2022
    extension.HISTORY_START = "2021-12-20"
    extension.main()
