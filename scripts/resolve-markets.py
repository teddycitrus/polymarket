"""Check unresolved markets and record their final outcomes.

    python scripts/resolve-markets.py

Scans the DB for markets that have a forecast but no resolution, re-fetches each
from Gamma, and if it has settled, writes the definitive binary outcome
(1.0 YES / 0.0 NO) into the resolutions table. Safe to run repeatedly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingest import fetch_market_by_id, resolved_outcome  # noqa: E402
from score import connect, insert_resolution, unresolved_market_ids  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve settled markets in the DB.")
    parser.add_argument("--db", default=None, help="SQLite path (default data/forecasts.db)")
    args = parser.parse_args()

    conn = connect(args.db) if args.db else connect()
    pending = unresolved_market_ids(conn)
    print(f"Unresolved markets with forecasts: {len(pending)}")
    if not pending:
        print("Nothing to resolve.")
        conn.close()
        return 0

    resolved = 0
    still_open = 0
    for market_id in pending:
        market = fetch_market_by_id(market_id)
        if market is None:
            print(f"  {market_id}: not found on Gamma (skipping)")
            continue
        outcome = resolved_outcome(market)
        if outcome is None:
            still_open += 1
            print(f"  {market_id}: still open ({market.question[:50]})")
            continue
        label = "YES" if outcome == 1.0 else "NO"
        insert_resolution(conn, market_id=market_id, resolved_yes=outcome, resolved_outcome_label=label)
        resolved += 1
        print(f"  {market_id}: RESOLVED {label} -> {market.question[:50]}")

    conn.close()
    print(f"\nDone. Newly resolved: {resolved} | still open: {still_open}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
