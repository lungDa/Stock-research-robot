"""Print a cached single-stock downside study as JSON."""
import argparse
import json

from app.services.defensive_research import report
from app.services.freshness import local_now


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('symbol', help='Taiwan stock symbol, e.g. 2317.TW')
    parser.add_argument('--min-pairs', type=int, default=60)
    parser.add_argument('--severe-drop', type=float, default=.02)
    args = parser.parse_args()
    try:
        result = report(args.symbol, local_now(), min_pairs=args.min_pairs,
                        severe_drop=args.severe_drop)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
