"""Brier scoring for forecast calibration.

Brier score for a single binary forecast:  B = (f - o)^2
  f = forecast probability of YES (0..1)
  o = actual outcome (1.0 if YES happened, 0.0 if NO)

Lower is better (0 = perfect, 1 = maximally wrong). We score the model and the
crowd price on the SAME resolved markets, so the difference isolates skill.

Net edge = market_brier - model_brier. Positive means the model is more
accurate than the crowd (it beats the market); negative means it does worse.
"""

from __future__ import annotations

from dataclasses import dataclass


def brier(forecast: float, outcome: float) -> float:
    return (forecast - outcome) ** 2


@dataclass
class BrierSummary:
    n_forecasts: int = 0
    model_brier: float | None = None
    market_brier: float | None = None

    @property
    def net_edge(self) -> float | None:
        if self.model_brier is None or self.market_brier is None:
            return None
        return self.market_brier - self.model_brier


def summarize(rows) -> BrierSummary:
    """Aggregate Brier scores over resolved-forecast rows.

    Each row must expose `ensemble_prob`, `crowd_price`, and `outcome`. The
    summary averages the per-forecast Brier scores for model and crowd.
    """
    model_scores: list[float] = []
    market_scores: list[float] = []
    for r in rows:
        outcome = float(r["outcome"])
        model_scores.append(brier(float(r["ensemble_prob"]), outcome))
        market_scores.append(brier(float(r["crowd_price"]), outcome))

    n = len(model_scores)
    return BrierSummary(
        n_forecasts=n,
        model_brier=sum(model_scores) / n if n else None,
        market_brier=sum(market_scores) / n if n else None,
    )
