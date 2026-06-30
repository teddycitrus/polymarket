"use strict";

const pct = x => (x === null || x === undefined) ? "n/a" : Math.round(x * 100) + "%";
const f4  = x => (x === null || x === undefined) ? "n/a" : x.toFixed(4);
const esc = s => (s || "").replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
const cls = x => x > 0 ? "pos" : x < 0 ? "neg" : "muted";

// Only render an outbound market link when the slug is a safe Polymarket slug,
// so API data can never inject a javascript:/data: URL into an href.
const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,191}$/;
const marketHref = slug => SLUG_RE.test(slug || "") ? `https://polymarket.com/event/${slug}` : null;

function renderCards(c) {
  const edge = c.net_edge;
  const edgeHtml = edge === null || edge === undefined
    ? '<span class="muted">n/a</span>'
    : `<span class="${cls(edge)}">${edge >= 0 ? "+" : ""}${f4(edge)}</span>`;
  document.getElementById("cards").innerHTML = `
    <div class="card"><div class="label">Tracked</div><div class="value">${c.tracked}</div></div>
    <div class="card"><div class="label">Resolved</div><div class="value">${c.resolved}</div></div>
    <div class="card"><div class="label">Scored</div><div class="value">${c.scored}</div></div>
    <div class="card"><div class="label">Model Brier</div><div class="value">${f4(c.model_brier)}</div></div>
    <div class="card"><div class="label">Market Brier</div><div class="value">${f4(c.market_brier)}</div></div>
    <div class="card"><div class="label">Net Edge</div><div class="value">${edgeHtml}</div></div>`;
}

function renderTrend(history) {
  const el = document.getElementById("trend");
  if (!history.length) { el.innerHTML = '<div class="empty">no resolved markets yet &mdash; edge is unknowable until markets settle</div>'; return; }
  let sum = 0;
  const pts = history.map((h, i) => { sum += (h.market_brier - h.model_brier); return sum / (i + 1); });
  const W = 920, H = 90, pad = 6;
  const min = Math.min(...pts, 0), max = Math.max(...pts, 0), span = (max - min) || 1;
  const x = i => pad + i * (W - 2 * pad) / Math.max(pts.length - 1, 1);
  const y = v => pad + (H - 2 * pad) * (1 - (v - min) / span);
  const line = pts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="none">
      <line x1="${pad}" y1="${y(0)}" x2="${W-pad}" y2="${y(0)}" stroke="#30363d" stroke-dasharray="3 3"/>
      <path d="${line}" fill="none" stroke="${last >= 0 ? "#3fb950" : "#f85149"}" stroke-width="2"/>
    </svg>
    <div class="${cls(last)}" style="font-size:12px;margin-top:6px">current cumulative net edge: ${last >= 0 ? "+" : ""}${f4(last)} ${history.length < 50 ? '<span class="muted">(noise until ~50 resolved)</span>' : ""}</div>`;
}

function renderMarkets(markets) {
  const el = document.getElementById("markets");
  if (!markets.length) { el.innerHTML = '<div class="empty">no forecasts yet &mdash; run the forecast endpoint</div>'; return; }
  const rows = markets.map(m => {
    const edge = m.edge;
    const big = (edge !== null && edge !== undefined && Math.abs(edge) >= 0.10) ? '<span class="pill">BIG GAP</span>' : "";
    const href = marketHref(m.slug);
    const title = href ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${esc(m.question)}</a>` : esc(m.question);
    const edgeCell = edge === null || edge === undefined ? '<span class="muted">n/a</span>'
      : `<span class="${cls(edge)}">${edge >= 0 ? "+" : ""}${Math.round(edge*100)} pts</span>`;
    return `<tr>
      <td class="q">${title}${big}</td>
      <td class="num">${pct(m.model)}</td>
      <td class="num muted">${pct(m.crowd)}</td>
      <td class="num">${edgeCell}</td>
    </tr>`;
  }).join("");
  el.innerHTML = `<table><thead><tr><th>Market</th><th class="num">Model</th><th class="num">Crowd</th><th class="num">Edge</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderHistory(history) {
  const el = document.getElementById("history");
  if (!history.length) { el.innerHTML = '<div class="empty">no resolved predictions yet</div>'; return; }
  const rows = history.slice().reverse().map(h => `<tr>
      <td class="q">${esc(h.question)}</td>
      <td class="num">${h.outcome == 1 ? '<span class="pos">YES</span>' : '<span class="neg">NO</span>'}</td>
      <td class="num">${pct(h.model)}</td>
      <td class="num muted">${pct(h.crowd)}</td>
      <td class="num">${f4(h.model_brier)}</td>
      <td class="num muted">${f4(h.market_brier)}</td>
    </tr>`).join("");
  el.innerHTML = `<table><thead><tr><th>Market</th><th class="num">Outcome</th><th class="num">Model</th><th class="num">Crowd</th><th class="num">Model B</th><th class="num">Mkt B</th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function load() {
  try {
    const res = await fetch("/api/dashboard", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    document.getElementById("error").innerHTML = "";
    renderCards(data.calibration);
    renderTrend(data.history);
    renderMarkets(data.markets);
    renderHistory(data.history);
    document.getElementById("updated").textContent = new Date().toLocaleString();
  } catch (e) {
    document.getElementById("error").innerHTML = `<div class="err">Failed to load /api/dashboard: ${esc(e.message)}</div>`;
  }
}

load();
setInterval(load, 60000);
