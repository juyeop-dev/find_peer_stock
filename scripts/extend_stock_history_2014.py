"""Prepend verified, compatible cached 2014 prices without changing later points."""
import extend_stock_history_2023 as extension


if __name__ == "__main__":
    extension.main(year=2014, cache_years=(2014,))
