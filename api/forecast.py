"""Vercel serverless function: run a batch forecast (write endpoint).

POST /api/forecast
  Header:  Authorization: Bearer <FORECAST_API_TOKEN>
  Body:    {"limit": 3, "low": 0.10, "high": 0.90}   (all optional)

Protected by a bearer token so random callers can't drain the Anthropic budget.
Selects liquid mid-tier political markets and routes each through the shared
ensemble engine, writing results to the (Turso) database.

Note: each market takes tens of seconds (web search + 3 ensemble runs), so keep
`limit` small and set a generous maxDuration in vercel.json.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

# Hard cap on markets per request. Each takes ~2 min, so this must stay small
# given the function's maxDuration. Raise FORECAST_MAX_LIMIT only if you've also
# raised maxDuration in vercel.json (needs Vercel Pro for >60s).
MAX_LIMIT = int(os.environ.get("FORECAST_MAX_LIMIT", "2"))

# Request body is a tiny JSON object; reject anything larger to bound memory.
MAX_BODY_BYTES = 4096

# Reject weak tokens so a misconfiguration can't leave a brute-forceable secret.
MIN_TOKEN_LEN = 24

# Security-event log. Goes to stderr (captured by Vercel). Never logs the token.
_log = logging.getLogger("api.forecast")
if not _log.handlers:
    logging.basicConfig(level=logging.INFO)


def _authorized(headers) -> bool:
    expected = os.environ.get("FORECAST_API_TOKEN")
    if not expected or len(expected) < MIN_TOKEN_LEN:
        if expected:
            _log.error("FORECAST_API_TOKEN shorter than %d chars; refusing all requests", MIN_TOKEN_LEN)
        return False  # fail closed if no/weak token is configured
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    # Constant-time comparison avoids leaking the token via response timing.
    return hmac.compare_digest(auth[7:].strip(), expected)


def run_batch(limit: int, low: float, high: float) -> dict:
    # Heavy imports (anthropic, the forecasting engine) are deferred to here so
    # that unauthorized requests return 401 without paying the import cost --
    # and so the auth path stays importable even where native deps are absent.
    from ingest import fetch_political_markets
    from pipeline import forecast_market
    from score import connect

    pool = fetch_political_markets(limit=200, min_volume=1000.0)
    selected = [m for m in pool if m.yes_price is not None and low < m.yes_price < high][:limit]

    conn = connect()
    results = []
    try:
        for market in selected:
            try:
                out = forecast_market(conn, market, runs=3, model="sonnet", max_news=5, verbose=False)
                results.append(
                    {
                        "market_id": market.id,
                        "question": market.question,
                        "model": out.ensemble.ensemble_prob,
                        "crowd": out.crowd_price,
                        "edge": out.edge,
                        "forecast_id": out.forecast_id,
                    }
                )
            except Exception:
                _log.exception("forecast failed for market %s", market.id)
                results.append({"market_id": market.id, "error": "forecast failed"})
    finally:
        conn.close()
    return {"requested": limit, "selected": len(selected), "forecasts": results}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        if not _authorized(self.headers):
            _log.warning("forecast auth failure")
            self._json(401, {"error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "invalid Content-Length"})
            return
        if length > MAX_BODY_BYTES:
            self._json(413, {"error": "request body too large"})
            return

        try:
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            # Clamp to a small batch: each market is ~2 min and the function has
            # a hard duration cap, so this bounds runtime and Anthropic spend.
            limit = max(1, min(int(body.get("limit", 1)), MAX_LIMIT))
            low = float(body.get("low", 0.10))
            high = float(body.get("high", 0.90))
        except (ValueError, TypeError, json.JSONDecodeError):
            self._json(400, {"error": "malformed request body"})
            return
        if not (0.0 <= low < high <= 1.0):
            self._json(400, {"error": "require 0 <= low < high <= 1"})
            return

        _log.info("forecast run requested: limit=%d band=%.2f-%.2f", limit, low, high)
        try:
            self._json(200, run_batch(limit, low, high))
        except Exception:
            # Log full detail server-side; return an opaque message to the client.
            _log.exception("forecast run failed")
            self._json(500, {"error": "internal error"})

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
