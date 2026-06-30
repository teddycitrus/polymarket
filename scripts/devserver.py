"""Local emulation of the Vercel deployment.

    python scripts/devserver.py     # then open http://localhost:3000

Serves index.html at / and routes /api/dashboard and /api/forecast to the real
serverless handler modules (loaded by file path, exactly as Vercel imports
them). Lets you exercise the whole stack -- frontend fetch -> API -> libSQL DB --
without a Vercel login. `vercel dev` does the same once you've run `vercel login`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dashboard = _load("api_dashboard", "api/dashboard.py")
forecast = _load("api_forecast", "api/forecast.py")


class Dispatcher(BaseHTTPRequestHandler):
    def _send(self, status, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # Explicit static whitelist (path -> file under public/) so the path is
    # never derived from the request -- no directory traversal possible.
    _STATIC = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/index.html": ("index.html", "text/html; charset=utf-8"),
        "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    }

    def do_GET(self):  # noqa: N802
        if self.path in self._STATIC:
            name, ctype = self._STATIC[self.path]
            with open(os.path.join(ROOT, "public", name), "rb") as f:
                self._send(200, f.read(), ctype)
        elif self.path.startswith("/api/dashboard"):
            try:
                self._send(200, json.dumps(dashboard.build_payload()).encode(), "application/json")
            except Exception:
                self._send(500, b'{"error":"internal error"}', "application/json")
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def do_POST(self):  # noqa: N802
        if not self.path.startswith("/api/forecast"):
            self._send(404, b'{"error":"not found"}', "application/json")
            return
        if not forecast._authorized(self.headers):
            self._send(401, b'{"error":"unauthorized"}', "application/json")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, b'{"error":"invalid Content-Length"}', "application/json")
            return
        if length > forecast.MAX_BODY_BYTES:
            self._send(413, b'{"error":"request body too large"}', "application/json")
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"{}") if length else {}
            if not isinstance(payload, dict):
                raise ValueError("body must be an object")
            limit = max(1, min(int(payload.get("limit", 1)), forecast.MAX_LIMIT))
            low = float(payload.get("low", 0.10))
            high = float(payload.get("high", 0.90))
            if not (0.0 <= low < high <= 1.0):
                raise ValueError("bad band")
        except (ValueError, TypeError, json.JSONDecodeError):
            self._send(400, b'{"error":"malformed request body"}', "application/json")
            return
        try:
            self._send(200, json.dumps(forecast.run_batch(limit, low, high)).encode(), "application/json")
        except Exception:
            self._send(500, b'{"error":"internal error"}', "application/json")

    def log_message(self, *args):
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Vercel emulation server.")
    parser.add_argument("--port", type=int, default=3000)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Dispatcher)
    print(f"Dev server on http://127.0.0.1:{args.port}  (/, /api/dashboard, POST /api/forecast)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
