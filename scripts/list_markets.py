"""Smoke test for the ingestion layer.

Pulls live political markets from Polymarket and prints the crowd's YES
probability next to each question. Run:

    python scripts/list_markets.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingest import fetch_political_markets, iter_market_summaries


def main() -> None:
    markets = fetch_political_markets(limit=15, min_volume=1000)
    if not markets:
        print("No political markets returned. The API or tag filtering may have changed.")
        return
    print("Live binary political markets (crowd YES prob | volume | question):\n")
    for m, line in zip(markets, iter_market_summaries(markets)):
        print(line)
        if m.event_title and m.event_title.lower() not in m.question.lower():
            print(f"          event: {m.event_title[:70]}")


if __name__ == "__main__":
    main()
