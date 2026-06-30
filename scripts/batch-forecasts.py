"""Batch forecast all liquid, mid-priced political markets.

    python scripts/batch-forecasts.py --limit 3

Pulls active political markets, keeps only liquid mid-tier ones (crowd YES price
strictly between 0.10 and 0.90 -- where there's real uncertainty and thus a
chance of edge), and routes each through the same 3x ensemble engine, appending
a timestamped forecast row per market to data/forecasts.db.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingest import Market, fetch_political_markets  # noqa: E402
from pipeline import forecast_market  # noqa: E402
from score import connect  # noqa: E402


def _in_band(market: Market, low: float, high: float) -> bool:
    p = market.yes_price
    return p is not None and low < p < high


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch-forecast mid-tier political markets.")
    parser.add_argument("--limit", type=int, default=5, help="max markets to forecast (default 5)")
    parser.add_argument("--low", type=float, default=0.10, help="lower price bound (exclusive)")
    parser.add_argument("--high", type=float, default=0.90, help="upper price bound (exclusive)")
    parser.add_argument("--min-volume", type=float, default=1000.0, help="minimum market volume")
    parser.add_argument("--runs", type=int, default=3, help="ensemble size per market")
    parser.add_argument("--model", default="sonnet", help="claude model alias")
    parser.add_argument("--max-news", type=int, default=5, help="news items per market")
    parser.add_argument("--db", default=None, help="SQLite path (default data/forecasts.db)")
    parser.add_argument("--dry-run", action="store_true", help="list selected markets, don't forecast")
    args = parser.parse_args()

    print("Fetching active political markets from Gamma...")
    # Pull a generous pool, then filter to the mid-price band.
    pool = fetch_political_markets(limit=200, min_volume=args.min_volume)
    selected = [m for m in pool if _in_band(m, args.low, args.high)][: args.limit]

    print(
        f"Pool: {len(pool)} political markets | "
        f"in band ({args.low}-{args.high}): {sum(_in_band(m, args.low, args.high) for m in pool)} | "
        f"forecasting: {len(selected)}\n"
    )
    if not selected:
        print("No markets matched the filter. Try widening the band or lowering --min-volume.")
        return 0

    for i, m in enumerate(selected, 1):
        print(f"[{i}/{len(selected)}] {m.question[:70]}  (crowd {m.yes_price:.2f}, vol {m.volume:,.0f})")

    if args.dry_run:
        print("\n--dry-run: no forecasts executed.")
        return 0

    conn = connect(args.db) if args.db else connect()
    failures = 0
    for i, market in enumerate(selected, 1):
        print(f"\n=== [{i}/{len(selected)}] {market.question[:70]} ===")
        try:
            out = forecast_market(conn, market, runs=args.runs, model=args.model, max_news=args.max_news)
            edge = f"{out.edge * 100:+.1f} pts" if out.edge is not None else "n/a"
            print(f"  -> stored id={out.forecast_id} | your {out.ensemble.ensemble_prob} vs crowd {out.crowd_price} | edge {edge}")
        except Exception as e:  # keep the batch going if one market fails
            failures += 1
            print(f"  -> ERROR forecasting market {market.id}: {type(e).__name__}: {e}")

    conn.close()
    print(f"\nDone. Forecasted {len(selected) - failures}/{len(selected)} markets ({failures} failed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
