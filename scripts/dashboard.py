"""Minimalist local dashboard for the forecasts.

    python scripts/dashboard.py        # then open http://localhost:8765

Pure stdlib (http.server) -- no Flask/Streamlit, no pip install. Reads the
SQLite DB fresh on every request, so it reflects the latest nightly run. Shows
open markets ranked by model/crowd disagreement, plus the calibration summary.
"""

from __future__ import annotations

import argparse
import html
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: #0e1116; color: #e6edf3;
       font: 14px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.wrap { max-width: 960px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px; letter-spacing: .3px; }
.sub { color: #7d8590; font-size: 12px; margin-bottom: 24px; }
.cal { display: flex; flex-wrap: wrap; gap: 18px; padding: 14px 18px; margin-bottom: 26px;
       background: #161b22; border: 1px solid #21262d; border-radius: 10px; }
.cal div { font-size: 12px; color: #7d8590; }
.cal b { display: block; font-size: 18px; color: #e6edf3; font-weight: 600; }
.edge-pos b { color: #3fb950; } .edge-neg b { color: #f85149; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .5px;
     color: #7d8590; font-weight: 600; padding: 8px 10px; border-bottom: 1px solid #21262d; }
td { padding: 12px 10px; border-bottom: 1px solid #161b22; vertical-align: top; }
tr:hover td { background: #11161d; }
.q { font-weight: 500; }
.q a { color: #e6edf3; text-decoration: none; }
.q a:hover { color: #58a6ff; text-decoration: underline; }
.rationale { color: #7d8590; font-size: 12px; margin-top: 4px; max-width: 520px; }
.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.pos { color: #3fb950; } .neg { color: #f85149; } .muted { color: #7d8590; }
.bar { height: 5px; border-radius: 3px; margin-top: 5px; background: #21262d; overflow: hidden; }
.bar i { display: block; height: 100%; }
.bar .pos { background: #3fb950; } .bar .neg { background: #f85149; }
.pill { font-size: 10px; padding: 1px 7px; border-radius: 999px; border: 1px solid #30363d; color: #7d8590; }
.empty { color: #7d8590; padding: 40px 0; text-align: center; }
footer { margin-top: 28px; color: #484f58; font-size: 11px; }
"""


def _pct(x) -> str:
    return f"{x * 100:.0f}%" if x is not None else "n/a"


def _row_html(rank: int, r) -> str:
    q = html.escape(r["question"] or "")
    slug = r["slug"] or ""
    link = f"https://polymarket.com/event/{html.escape(slug)}" if slug else "#"
    edge = r["edge"]
    model = r["ensemble_prob"]
    crowd = r["crowd_price"]
    summary = html.escape(r["summary"] or "")

    if edge is None:
        edge_cell = '<span class="muted">n/a</span>'
        bar = ""
    else:
        cls = "pos" if edge > 0 else "neg"
        edge_cell = f'<span class="{cls}">{edge * 100:+.0f} pts</span>'
        width = min(abs(edge) * 100 * 2, 100)  # 50pt gap == full bar
        bar = f'<div class="bar"><i class="{cls}" style="width:{width:.0f}%"></i></div>'

    big = ' <span class="pill">BIG GAP</span>' if edge is not None and abs(edge) >= 0.10 else ""
    rationale = f'<div class="rationale">{summary}</div>' if summary else ""

    return f"""<tr>
      <td class="num muted">{rank}</td>
      <td class="q"><a href="{link}" target="_blank" rel="noopener">{q}</a>{big}{rationale}</td>
      <td class="num">{_pct(model)}</td>
      <td class="num muted">{_pct(crowd)}</td>
      <td class="num">{edge_cell}{bar}</td>
    </tr>"""


def render_page(conn) -> str:
    rows = latest_forecasts(conn)
    summary = summarize(resolved_forecasts(conn))
    now = datetime.now().strftime("%a %Y-%m-%d %H:%M")

    if summary.net_edge is None:
        edge_block = '<div><b class="muted">n/a</b>net edge<br><span style="font-size:11px">(no resolutions yet)</span></div>'
    else:
        sign_cls = "edge-pos" if summary.net_edge > 0 else "edge-neg"
        note = " (noise &lt;50)" if summary.n_forecasts < 50 else ""
        edge_block = (
            f'<div class="{sign_cls}"><b>{summary.net_edge:+.4f}</b>net edge{note}</div>'
            f'<div><b>{summary.model_brier:.4f}</b>model Brier</div>'
            f'<div><b>{summary.market_brier:.4f}</b>market Brier</div>'
        )

    if rows:
        body = "\n".join(_row_html(i, r) for i, r in enumerate(rows, 1))
        table = f"""<table>
          <thead><tr>
            <th class="num">#</th><th>Market</th>
            <th class="num">Model</th><th class="num">Crowd</th><th class="num">Edge</th>
          </tr></thead>
          <tbody>{body}</tbody>
        </table>"""
    else:
        table = '<div class="empty">No forecasts yet. Run <code>python scripts/batch-forecasts.py</code>.</div>'

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Polymarket Forecaster</title>
<style>{_CSS}</style>
</head><body><div class="wrap">
  <h1>Polymarket Forecaster</h1>
  <div class="sub">paper-trading research &middot; open markets ranked by model/crowd disagreement &middot; {now}</div>
  <div class="cal">
    <div><b>{count_markets(conn)}</b>tracked</div>
    <div><b>{count_resolved(conn)}</b>resolved</div>
    <div><b>{summary.n_forecasts}</b>scored</div>
    {edge_block}
  </div>
  {table}
  <footer>auto-refreshes every 60s &middot; data/forecasts.db</footer>
</div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    db_path = None

    def do_GET(self):  # noqa: N802
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        conn = connect(self.db_path) if self.db_path else connect()
        try:
            page = render_page(conn).encode("utf-8")
        finally:
            conn.close()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, *args):  # quiet
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the forecast dashboard.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--db", default=None, help="SQLite path (default data/forecasts.db)")
    args = parser.parse_args()

    Handler.db_path = args.db
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Dashboard running at {url}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
