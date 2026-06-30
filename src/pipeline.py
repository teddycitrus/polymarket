"""Shared single-market forecasting engine.

Both scripts/run-forecasts.py (one slug) and scripts/batch-forecasts.py (many
markets) call forecast_market() so the core loop lives in exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from forecast import EnsembleResult, run_ensemble
from ingest import Market, live_yes_price
from retrieve import NewsItem, fetch_news
from score import insert_forecast, upsert_market


@dataclass
class PipelineOutput:
    market: Market
    crowd_price: float | None
    news: list[NewsItem]
    ensemble: EnsembleResult
    forecast_id: int
    edge: float | None


def _fmt_pct(x: float | None) -> str:
    return f"{x * 100:5.1f}%" if x is not None else "  n/a"


def forecast_market(
    conn,
    market: Market,
    *,
    runs: int = 3,
    model: str = "sonnet",
    max_news: int = 5,
    verbose: bool = True,
) -> PipelineOutput:
    def log(msg: str) -> None:
        if verbose:
            print(msg)

    crowd = live_yes_price(market)
    log(f"  crowd YES probability: {_fmt_pct(crowd)}")

    topic = market.question if not market.event_title else f"{market.event_title} - {market.question}"
    log(f"  retrieving up to {max_news} news items...")
    news = fetch_news(topic, max_items=max_news)
    log(f"  got {len(news)} news items")

    log(f"  running {runs}x ensemble ({model})...")
    ens = run_ensemble(
        question=market.question,
        resolution=market.description,
        news_lines=[n.as_line() for n in news],
        today=date.today().isoformat(),
        event_title=market.event_title,
        runs=runs,
        model=model,
    )
    for r in ens.runs:
        status = _fmt_pct(r.prob) if r.parse_ok else f"FAILED ({r.error})"
        log(f"    run {r.index}: {status}  [{r.confidence or '-'}]")

    upsert_market(conn, market)
    runs_payload = [
        {"index": r.index, "prob": r.prob, "confidence": r.confidence, "summary": r.summary, "parse_ok": r.parse_ok}
        for r in ens.runs
    ]
    best_summary = next((r.summary for r in ens.runs if r.summary), "")
    from dataclasses import asdict

    fid = insert_forecast(
        conn,
        market_id=market.id,
        crowd_price=crowd,
        ensemble_prob=ens.ensemble_prob,
        n_valid=ens.n_valid,
        n_runs=runs,
        model=model,
        runs=runs_payload,
        news=[asdict(n) for n in news],
        summary=best_summary,
    )

    edge = None
    if ens.ensemble_prob is not None and crowd is not None:
        edge = ens.ensemble_prob - crowd

    return PipelineOutput(
        market=market, crowd_price=crowd, news=news, ensemble=ens, forecast_id=fid, edge=edge
    )


def print_summary(out: PipelineOutput, runs: int) -> None:
    ens = out.ensemble
    print("\n" + "=" * 64)
    print(" FORECAST SUMMARY")
    print("=" * 64)
    print(f" Market      : {out.market.question}")
    print(f" Your prob   : {_fmt_pct(ens.ensemble_prob)}   ({ens.n_valid}/{runs} runs valid)")
    print(f" Market prob : {_fmt_pct(out.crowd_price)}")
    if out.edge is not None:
        direction = "model says YES underpriced" if out.edge > 0 else "model says YES overpriced"
        print(f" Edge gap    : {out.edge * 100:+5.1f} pts   ({direction})")
    else:
        print(" Edge gap    :   n/a   (missing a probability)")
    best_summary = next((r.summary for r in ens.runs if r.summary), "")
    print(f" Rationale   : {best_summary or '(no summary parsed)'}")
    print("=" * 64)
