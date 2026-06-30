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

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

# Hard cap on markets per request. Each takes ~2 min, so this must stay small
# given the function's maxDuration. Raise FORECAST_MAX_LIMIT only if you've also
# raised maxDuration in vercel.json (needs Vercel Pro for >60s).
MAX_LIMIT = int(os.environ.get("FORECAST_MAX_LIMIT", "2"))


def _authorized(headers) -> bool:
    expected = os.environ.get("FORECAST_API_TOKEN")
    if not expected:
        return False  # fail closed if no token configured
    auth = headers.get("Authorization", "")
    return auth.startswith("Bearer ") and auth[7:].strip() == expected


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
            except Exception as e:
                results.append({"market_id": market.id, "error": f"{type(e).__name__}: {e}"})
    finally:
        conn.close()
    return {"requested": limit, "selected": len(selected), "forecasts": results}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        if not _authorized(self.headers):
            self._json(401, {"error": "unauthorized: valid Bearer token required"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            # Clamp to a small batch: each market is ~2 min, and the function has
            # a hard duration cap. MAX_LIMIT keeps a single request from timing
            # out or running up an unexpected Anthropic bill.
            limit = max(1, min(int(body.get("limit", 1)), MAX_LIMIT))
            low = float(body.get("low", 0.10))
            high = float(body.get("high", 0.90))
        except (ValueError, json.JSONDecodeError) as e:
            self._json(400, {"error": f"bad request body: {e}"})
            return

        try:
            self._json(200, run_batch(limit, low, high))
        except Exception as e:
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
