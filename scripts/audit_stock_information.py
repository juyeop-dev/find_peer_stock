"""Audit actual published financial/history observations for a configured range."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from financial_history_request import financial_request
from history_policy import DEFAULT_POLICY
import audit_stock_information_2024_h2 as audit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-config", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--year", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        request = financial_request(year=args.year, config=args.history_config, root=audit.information.ROOT)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.dry_run:
        print(json.dumps(asdict(request), default=str)); return
    audit.main(request)


if __name__ == "__main__":
    main()
