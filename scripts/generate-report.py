"""Calibration report: are we beating the crowd?

    python scripts/generate-report.py

Joins every forecast on a resolved market to its outcome, computes Brier scores
for the model and the crowd price (captured at forecast time), and prints the
cumulative paper-trading edge.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from score import (  # noqa: E402
    brier,
    connect,
    count_markets,
    count_resolved,
    resolved_forecasts,
    summarize,
)


def _fmt(x: float | None, places: int = 4) -> str:
    return f"{x:.{places}f}" if x is not None else "n/a"


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the calibration / edge report.")
    parser.add_argument("--db", default=None, help="SQLite path (default data/forecasts.db)")
    parser.add_argument("--detail", action="store_true", help="show per-forecast Brier breakdown")
    args = parser.parse_args()

    conn = connect(args.db) if args.db else connect()
    total_markets = count_markets(conn)
    total_resolved = count_resolved(conn)
    rows = resolved_forecasts(conn)
    summary = summarize(rows)
    conn.close()

    print("=" * 60)
    print(" POLYMARKET FORECASTER - CALIBRATION REPORT")
    print("=" * 60)
    print(f" Markets tracked        : {total_markets}")
    print(f" Markets resolved       : {total_resolved}")
    print(f" Scored forecasts       : {summary.n_forecasts}")
    print("-" * 60)
    print(f" Model Brier score      : {_fmt(summary.model_brier)}   (lower is better)")
    print(f" Market Brier score     : {_fmt(summary.market_brier)}   (lower is better)")
    print("-" * 60)

    edge = summary.net_edge
    if edge is None:
        print(" Net edge               : n/a  (no resolved forecasts yet)")
        print("\n Forecast some markets, wait for them to resolve, then re-run.")
    else:
        verdict = "BEATING the market" if edge > 0 else "LOSING to the market" if edge < 0 else "matching the market"
        print(f" NET EDGE (mkt - model) : {edge:+.4f}   -> {verdict}")
        if summary.n_forecasts < 50:
            print(f"\n NOTE: only {summary.n_forecasts} scored forecasts. Treat as noise until ~50+.")
    print("=" * 60)

    if args.detail and rows:
        print("\n Per-forecast detail:")
        print(f"   {'outcome':>7}  {'model':>6}  {'crowd':>6}  {'mB':>6}  {'cB':>6}  question")
        for r in rows:
            o = float(r["outcome"])
            mb = brier(float(r["ensemble_prob"]), o)
            cb = brier(float(r["crowd_price"]), o)
            print(
                f"   {o:>7.0f}  {r['ensemble_prob']:>6.2f}  {r['crowd_price']:>6.2f}  "
                f"{mb:>6.3f}  {cb:>6.3f}  {r['question'][:40]}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
