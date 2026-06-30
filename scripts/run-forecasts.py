"""End-to-end forecast for a single political market.

    python scripts/run-forecasts.py --slug <market-slug>

Pipeline: ingest market (Gamma) -> live price (CLOB) -> news (web search) ->
3x ensemble forecast (Claude) -> store (SQLite) -> print edge summary.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingest import fetch_market_by_slug  # noqa: E402
from pipeline import forecast_market, print_summary  # noqa: E402
from score import connect  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Forecast a single Polymarket market.")
    parser.add_argument("--slug", required=True, help="Polymarket market slug")
    parser.add_argument("--runs", type=int, default=3, help="ensemble size (default 3)")
    parser.add_argument("--model", default="sonnet", help="claude model alias (default sonnet)")
    parser.add_argument("--max-news", type=int, default=5, help="news items to retrieve")
    parser.add_argument("--db", default=None, help="SQLite path (default data/forecasts.db)")
    args = parser.parse_args()

    print(f"[1/2] Fetching market '{args.slug}' from Gamma...")
    market = fetch_market_by_slug(args.slug)
    if market is None:
        print(f"  ERROR: no market found for slug '{args.slug}'")
        return 2
    print(f"      {market.question}")
    if not market.is_binary_yes_no:
        print(f"  ERROR: market is not Yes/No (outcomes={market.outcomes}); pick a binary market.")
        return 2

    print("[2/2] Running pipeline (price -> news -> ensemble -> store)...")
    conn = connect(args.db) if args.db else connect()
    out = forecast_market(conn, market, runs=args.runs, model=args.model, max_news=args.max_news)
    conn.close()
    print(f"      stored forecast id={out.forecast_id}")

    print_summary(out, args.runs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
