"""Copy the local SQLite database into the Turso cloud database.

    # with TURSO_DATABASE_URL and TURSO_AUTH_TOKEN set in the environment
    python scripts/migrate-to-turso.py

Copies markets, forecasts, and resolutions from the local data/forecasts.db
into Turso. Idempotent: markets and resolutions upsert by primary key, and
forecasts dedupe on (market_id, ts), so re-running does not create duplicates.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from score import DEFAULT_DB, connect_libsql  # noqa: E402


def _copy_markets(src, dst) -> int:
    rows = src.execute(
        "SELECT id, slug, question, description, event_title, event_slug, end_date, outcomes, created_at, updated_at FROM markets"
    ).fetchall()
    for r in rows:
        dst.execute(
            """
            INSERT INTO markets (id, slug, question, description, event_title, event_slug, end_date, outcomes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                slug=excluded.slug, question=excluded.question, description=excluded.description,
                event_title=excluded.event_title, event_slug=excluded.event_slug, end_date=excluded.end_date,
                outcomes=excluded.outcomes, updated_at=excluded.updated_at
            """,
            (r["id"], r["slug"], r["question"], r["description"], r["event_title"], r["event_slug"],
             r["end_date"], r["outcomes"], r["created_at"], r["updated_at"]),
        )
    return len(rows)


def _copy_forecasts(src, dst) -> int:
    rows = src.execute(
        """SELECT market_id, ts, crowd_price, ensemble_prob, edge, n_valid, n_runs, model, runs_json, news_json, summary
           FROM forecasts"""
    ).fetchall()
    inserted = 0
    for r in rows:
        # Forecasts are append-only with no natural key; dedupe on (market_id, ts).
        exists = dst.execute(
            "SELECT 1 FROM forecasts WHERE market_id=? AND ts=? LIMIT 1", (r["market_id"], r["ts"])
        ).fetchone()
        if exists:
            continue
        dst.execute(
            """
            INSERT INTO forecasts
                (market_id, ts, crowd_price, ensemble_prob, edge, n_valid, n_runs, model, runs_json, news_json, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (r["market_id"], r["ts"], r["crowd_price"], r["ensemble_prob"], r["edge"], r["n_valid"],
             r["n_runs"], r["model"], r["runs_json"], r["news_json"], r["summary"]),
        )
        inserted += 1
    return inserted


def _copy_resolutions(src, dst) -> int:
    rows = src.execute(
        "SELECT market_id, resolved_outcome, resolved_yes, resolved_at FROM resolutions"
    ).fetchall()
    for r in rows:
        dst.execute(
            """
            INSERT INTO resolutions (market_id, resolved_outcome, resolved_yes, resolved_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(market_id) DO UPDATE SET
                resolved_outcome=excluded.resolved_outcome,
                resolved_yes=excluded.resolved_yes,
                resolved_at=excluded.resolved_at
            """,
            (r["market_id"], r["resolved_outcome"], r["resolved_yes"], r["resolved_at"]),
        )
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate the local DB into Turso.")
    parser.add_argument("--src", default=str(DEFAULT_DB), help="local SQLite file (default data/forecasts.db)")
    args = parser.parse_args()

    turso_url = os.environ.get("TURSO_DATABASE_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")
    if not turso_url or not turso_token:
        print("ERROR: set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in the environment first.")
        return 2

    src_path = Path(args.src)
    if not src_path.exists():
        print(f"ERROR: local database not found at {src_path}")
        return 2

    src = connect_libsql("file:" + str(src_path).replace("\\", "/"))
    dst = connect_libsql(turso_url, turso_token)
    try:
        m = _copy_markets(src, dst)
        f = _copy_forecasts(src, dst)
        r = _copy_resolutions(src, dst)
    finally:
        src.close()
        dst.close()

    print(f"Migrated to Turso: markets upserted={m}, forecasts inserted={f}, resolutions upserted={r}")
    print("Re-runs are safe (markets/resolutions upsert, forecasts dedupe on market_id+ts).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
