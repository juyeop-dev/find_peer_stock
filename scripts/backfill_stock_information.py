"""Collect financials for the configured date range; legacy year commands remain available."""
from financial_history_request import financial_request
from backfill_stock_information_2024_h2 import main


if __name__ == "__main__":
    main(request=financial_request())
