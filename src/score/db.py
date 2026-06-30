"""Persistence layer, backed by libSQL (Turso in the cloud, local file otherwise).

Connection routing:
- If TURSO_DATABASE_URL is set, connect to the hosted Turso instance (with
  TURSO_AUTH_TOKEN). All reads and writes go to the cloud.
- Otherwise, fall back to a local SQLite file via libSQL's `file:` URL.

Both paths use the same libsql-client code, so local runs exercise the exact
cloud query path. A thin adapter (Conn / _Result) preserves the small sqlite3
style surface the rest of the codebase already uses (execute().fetchone(),
fetchall(), lastrowid, commit()).

Three tables: markets, forecasts (append-only, timestamped), resolutions.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import libsql_client

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "forecasts.db"

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS markets (
        id           TEXT PRIMARY KEY,
        slug         TEXT,
        question     TEXT NOT NULL,
        description  TEXT,
        event_title  TEXT,
        event_slug   TEXT,
        end_date     TEXT,
        outcomes     TEXT,
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS forecasts (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        market_id     TEXT NOT NULL,
        ts            TEXT NOT NULL,
        crowd_price   REAL,
        ensemble_prob REAL,
        edge          REAL,
        n_valid       INTEGER,
        n_runs        INTEGER,
        model         TEXT,
        runs_json     TEXT,
        news_json     TEXT,
        summary       TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resolutions (
        market_id        TEXT PRIMARY KEY,
        resolved_outcome TEXT,
        resolved_yes     REAL,
        resolved_at      TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_forecasts_market ON forecasts(market_id, ts)",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Result:
    """sqlite3-cursor-like view over a libsql ResultSet."""

    def __init__(self, rs):
        self._rs = rs

    def fetchone(self):
        return self._rs.rows[0] if self._rs.rows else None

    def fetchall(self) -> list:
        return list(self._rs.rows)

    @property
    def lastrowid(self):
        return self._rs.last_insert_rowid


class Conn:
    """Minimal sqlite3-Connection-compatible wrapper around a libsql client."""

    def __init__(self, client):
        self._client = client

    def execute(self, sql: str, params: tuple | list = ()) -> _Result:
        if params:
            rs = self._client.execute(sql, list(params))
        else:
            rs = self._client.execute(sql)
        return _Result(rs)

    def executescript(self, statements: list[str]) -> None:
        self._client.batch(statements)

    def commit(self) -> None:
        # libsql autocommits each execute; nothing to flush.
        pass

    def close(self) -> None:
        self._client.close()


def _normalize_scheme(url: str) -> str:
    # libsql-client's sync client opens a WebSocket for libsql://, wss://, and
    # ws:// URLs. WebSocket transport is unreliable in short-lived serverless
    # functions, so force the stateless HTTP (Hrana-over-HTTP) transport, which
    # is what Turso's libsql:// URL points at anyway.
    for ws_scheme, http_scheme in (("libsql://", "https://"), ("wss://", "https://"), ("ws://", "http://")):
        if url.startswith(ws_scheme):
            return http_scheme + url[len(ws_scheme):]
    return url


def _resolve_url(db_path: str | Path | None) -> tuple[str, str | None]:
    turso = os.environ.get("TURSO_DATABASE_URL")
    if turso:
        return turso, os.environ.get("TURSO_AUTH_TOKEN")
    path = Path(db_path) if db_path else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    return "file:" + str(path).replace("\\", "/"), None


def connect_libsql(url: str, auth_token: str | None = None) -> Conn:
    """Connect to an explicit libSQL URL (file:, https://, libsql://, ...).

    Used directly when you need two connections at once (e.g. migrating a local
    file to Turso) rather than the env-driven default from connect().
    """
    url = _normalize_scheme(url)
    if auth_token:
        client = libsql_client.create_client_sync(url=url, auth_token=auth_token)
    else:
        client = libsql_client.create_client_sync(url=url)
    conn = Conn(client)
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: Conn) -> None:
    """Idempotent additive migrations for databases created by older schemas."""
    try:
        conn.execute("ALTER TABLE markets ADD COLUMN event_slug TEXT")
    except Exception:
        pass  # column already exists


def connect(db_path: str | Path | None = None) -> Conn:
    url, auth = _resolve_url(db_path)
    return connect_libsql(url, auth)


def upsert_market(conn: Conn, market) -> None:
    now = _now()
    conn.execute(
        """
        INSERT INTO markets (id, slug, question, description, event_title, event_slug, end_date, outcomes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            slug=excluded.slug, question=excluded.question, description=excluded.description,
            event_title=excluded.event_title, event_slug=excluded.event_slug, end_date=excluded.end_date,
            outcomes=excluded.outcomes, updated_at=excluded.updated_at
        """,
        (
            market.id,
            market.slug,
            market.question,
            market.description,
            market.event_title,
            market.event_slug,
            market.end_date,
            json.dumps(market.outcomes),
            now,
            now,
        ),
    )


def insert_forecast(
    conn: Conn,
    *,
    market_id: str,
    crowd_price: float | None,
    ensemble_prob: float | None,
    n_valid: int,
    n_runs: int,
    model: str,
    runs: list[dict],
    news: list[dict],
    summary: str,
) -> int:
    edge = None
    if ensemble_prob is not None and crowd_price is not None:
        edge = ensemble_prob - crowd_price
    cur = conn.execute(
        """
        INSERT INTO forecasts
            (market_id, ts, crowd_price, ensemble_prob, edge, n_valid, n_runs, model, runs_json, news_json, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            market_id,
            _now(),
            crowd_price,
            ensemble_prob,
            edge,
            n_valid,
            n_runs,
            model,
            json.dumps(runs),
            json.dumps(news),
            summary,
        ),
    )
    return int(cur.lastrowid)


def market_has_forecast(conn: Conn, market_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM forecasts WHERE market_id=? LIMIT 1", (market_id,)).fetchone()
    return row is not None


def unresolved_market_ids(conn: Conn) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT m.id AS id
        FROM markets m
        JOIN forecasts f ON f.market_id = m.id
        WHERE m.id NOT IN (SELECT market_id FROM resolutions)
        """
    ).fetchall()
    return [r["id"] for r in rows]


def insert_resolution(
    conn: Conn,
    *,
    market_id: str,
    resolved_yes: float,
    resolved_outcome_label: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO resolutions (market_id, resolved_outcome, resolved_yes, resolved_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(market_id) DO UPDATE SET
            resolved_outcome=excluded.resolved_outcome,
            resolved_yes=excluded.resolved_yes,
            resolved_at=excluded.resolved_at
        """,
        (market_id, resolved_outcome_label, resolved_yes, _now()),
    )


def resolved_forecasts(conn: Conn) -> list[Any]:
    return conn.execute(
        """
        SELECT
            f.id            AS forecast_id,
            f.market_id     AS market_id,
            m.question      AS question,
            f.ts            AS ts,
            f.crowd_price   AS crowd_price,
            f.ensemble_prob AS ensemble_prob,
            r.resolved_yes  AS outcome
        FROM forecasts f
        JOIN resolutions r ON r.market_id = f.market_id
        JOIN markets m ON m.id = f.market_id
        WHERE f.ensemble_prob IS NOT NULL AND f.crowd_price IS NOT NULL
        ORDER BY f.ts
        """
    ).fetchall()


def latest_forecasts(conn: Conn) -> list[Any]:
    return conn.execute(
        """
        SELECT
            f.market_id     AS market_id,
            m.question      AS question,
            m.slug          AS slug,
            m.event_slug    AS event_slug,
            f.ts            AS ts,
            f.crowd_price   AS crowd_price,
            f.ensemble_prob AS ensemble_prob,
            f.edge          AS edge,
            f.n_valid       AS n_valid,
            f.n_runs        AS n_runs,
            f.summary       AS summary
        FROM forecasts f
        JOIN markets m ON m.id = f.market_id
        JOIN (SELECT market_id, MAX(ts) AS mts FROM forecasts GROUP BY market_id) latest
            ON latest.market_id = f.market_id AND latest.mts = f.ts
        WHERE f.market_id NOT IN (SELECT market_id FROM resolutions)
        ORDER BY ABS(COALESCE(f.edge, 0)) DESC
        """
    ).fetchall()


def count_markets(conn: Conn) -> int:
    return int(conn.execute("SELECT COUNT(*) AS c FROM markets").fetchone()["c"])


def count_resolved(conn: Conn) -> int:
    return int(conn.execute("SELECT COUNT(*) AS c FROM resolutions").fetchone()["c"])
