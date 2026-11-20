"""Reconstruct dated sector observations for an explicit configured range."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from collection_request import collection_request
from history_policy import DEFAULT_POLICY
import backfill_sector_history_2024 as sectors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int)
    parser.add_argument("--history-config", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        request = collection_request(year=args.year, config=args.history_config, root=sectors.ROOT)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.dry_run:
        print(json.dumps(asdict(request), default=str)); return
    sectors.main(year=int(request.start[:4]), end_before=None, audit_scope=request.scope, request=request)


if __name__ == "__main__":
    main()
