"""Vercel serverless function: read-only dashboard metrics as JSON.

GET /api/dashboard -> {
  calibration: {tracked, resolved, scored, model_brier, market_brier, net_edge},
  markets:      [ {question, slug, model, crowd, edge, ts}, ... ],   # open, by |edge|
  history:      [ {question, ts, model, crowd, outcome, model_brier, market_brier}, ... ]
}
"""

from __future__ import annotations

import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

_log = logging.getLogger("api.dashboard")
if not _log.handlers:
    logging.basicConfig(level=logging.INFO)

from score import (  # noqa: E402
    connect,
    count_markets,
    count_resolved,
    latest_forecasts,
    resolved_forecasts,
    summarize,
)
from score.brier import brier  # noqa: E402


def build_payload() -> dict:
    conn = connect()
    try:
        rows = latest_forecasts(conn)
        resolved = resolved_forecasts(conn)
        summary = summarize(resolved)
        payload = {
            "calibration": {
                "tracked": count_markets(conn),
                "resolved": count_resolved(conn),
                "scored": summary.n_forecasts,
                "model_brier": summary.model_brier,
                "market_brier": summary.market_brier,
                "net_edge": summary.net_edge,
            },
            "markets": [
                {
                    "question": r["question"],
                    "slug": r["event_slug"] or r["slug"],
                    "model": r["ensemble_prob"],
                    "crowd": r["crowd_price"],
                    "edge": r["edge"],
                    "ts": r["ts"],
                }
                for r in rows
            ],
            "history": [
                {
                    "question": r["question"],
                    "ts": r["ts"],
                    "model": r["ensemble_prob"],
                    "crowd": r["crowd_price"],
                    "outcome": r["outcome"],
                    "model_brier": brier(float(r["ensemble_prob"]), float(r["outcome"])),
                    "market_brier": brier(float(r["crowd_price"]), float(r["outcome"])),
                }
                for r in resolved
            ],
        }
    finally:
        conn.close()
    return payload


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        try:
            body = json.dumps(build_payload()).encode("utf-8")
            status = 200
        except Exception:
            _log.exception("dashboard build failed")
            body = b'{"error": "internal error"}'
            status = 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
