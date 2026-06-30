"""Your morning forecast board.

    python scripts/morning.py

Shows the latest forecast for each open market, ranked by how much the model
disagrees with the crowd (biggest edge first -- the markets worth a look), then
the running calibration summary. This is the one command to run each morning.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from score import (  # noqa: E402
    connect,
    count_markets,
    count_resolved,
    latest_forecasts,
    resolved_forecasts,
    summarize,
)


def _pct(x) -> str:
    return f"{x * 100:4.0f}%" if x is not None else " n/a"


def render(conn, top: int) -> str:
    lines: list[str] = []
    now = datetime.now().strftime("%a %Y-%m-%d %H:%M")
    lines.append("=" * 72)
    lines.append(f" POLYMARKET MORNING BOARD - {now}")
    lines.append("=" * 72)

    rows = latest_forecasts(conn)
    if not rows:
        lines.append(" No open forecasts yet. Run: python scripts/batch-forecasts.py")
    else:
        lines.append(f" Top {min(top, len(rows))} open markets by model/crowd disagreement:")
        lines.append("")
        lines.append(f"   {'EDGE':>6}  {'MODEL':>5}  {'CROWD':>5}  MARKET")
        lines.append("   " + "-" * 66)
        for r in rows[:top]:
            edge = r["edge"]
            edge_str = f"{edge * 100:+5.0f}p" if edge is not None else "  n/a"
            flag = ""
            if edge is not None and abs(edge) >= 0.10:
                flag = "  <== big gap"
            lines.append(
                f"   {edge_str:>6}  {_pct(r['ensemble_prob'])}  {_pct(r['crowd_price'])}  "
                f"{r['question'][:42]}{flag}"
            )
        lines.append("")
        # Show the rationale for the single biggest-edge market as a teaser.
        top_row = rows[0]
        if top_row["summary"]:
            lines.append(f" Biggest gap rationale ({top_row['question'][:40]}):")
            lines.append(f"   {top_row['summary']}")
            lines.append("")

    # Calibration line
    summary = summarize(resolved_forecasts(conn))
    lines.append("-" * 72)
    lines.append(
        f" Tracked: {count_markets(conn)} markets | "
        f"resolved: {count_resolved(conn)} | scored forecasts: {summary.n_forecasts}"
    )
    if summary.net_edge is None:
        lines.append(" Net edge: n/a (no markets resolved yet -- edge is unknowable until they settle)")
    else:
        verdict = "beating" if summary.net_edge > 0 else "losing to" if summary.net_edge < 0 else "matching"
        note = "  [NOISE until ~50+ resolved]" if summary.n_forecasts < 50 else ""
        lines.append(
            f" Net edge: {summary.net_edge:+.4f} ({verdict} the market) | "
            f"model Brier {summary.model_brier:.4f} vs market {summary.market_brier:.4f}{note}"
        )
    lines.append("=" * 72)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the morning forecast board.")
    parser.add_argument("--top", type=int, default=15, help="how many markets to show")
    parser.add_argument("--db", default=None, help="SQLite path (default data/forecasts.db)")
    args = parser.parse_args()

    conn = connect(args.db) if args.db else connect()
    print(render(conn, args.top))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
