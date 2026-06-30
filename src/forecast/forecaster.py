"""Ensemble forecaster: run the 5-step prompt N times and average.

Each run is an independent sample; averaging several reduces variance and
improves calibration. Runs that fail to parse are kept (for the audit trail)
but excluded from the average.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from forecast.prompt import build_forecast_prompt
from llm import DEFAULT_MODEL, LLMError, call_claude

_PROB_RE = re.compile(r"FINAL_PROBABILITY:\s*([0-9]*\.?[0-9]+)\s*(%?)", re.IGNORECASE)
_CONF_RE = re.compile(r"CONFIDENCE:\s*(low|medium|high)", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"SUMMARY:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


@dataclass
class ForecastRun:
    index: int
    prob: float | None
    confidence: str | None
    summary: str
    raw: str
    parse_ok: bool
    error: str | None = None


@dataclass
class EnsembleResult:
    runs: list[ForecastRun] = field(default_factory=list)
    ensemble_prob: float | None = None
    n_valid: int = 0

    @property
    def confidences(self) -> list[str]:
        return [r.confidence for r in self.runs if r.confidence]


def _parse_run(index: int, raw: str) -> ForecastRun:
    prob_m = _PROB_RE.search(raw)
    conf_m = _CONF_RE.search(raw)
    sum_m = _SUMMARY_RE.search(raw)
    prob: float | None = None
    if prob_m:
        val = float(prob_m.group(1))
        if prob_m.group(2) == "%" or val > 1.0:  # tolerate "20%" or "20"
            val = val / 100.0
        prob = min(max(val, 0.0), 1.0)
    return ForecastRun(
        index=index,
        prob=prob,
        confidence=conf_m.group(1).lower() if conf_m else None,
        summary=sum_m.group(1).strip() if sum_m else "",
        raw=raw,
        parse_ok=prob is not None,
        error=None if prob is not None else "no FINAL_PROBABILITY found",
    )


def run_ensemble(
    *,
    question: str,
    resolution: str,
    news_lines: list[str],
    today: str,
    event_title: str = "",
    runs: int = 3,
    model: str = DEFAULT_MODEL,
    timeout: int = 240,
) -> EnsembleResult:
    prompt = build_forecast_prompt(
        question=question,
        resolution=resolution,
        news_lines=news_lines,
        today=today,
        event_title=event_title,
    )
    result = EnsembleResult()
    for i in range(1, runs + 1):
        try:
            raw = call_claude(prompt, model=model, timeout=timeout)
            result.runs.append(_parse_run(i, raw))
        except LLMError as e:
            result.runs.append(
                ForecastRun(index=i, prob=None, confidence=None, summary="", raw="", parse_ok=False, error=str(e))
            )

    valid = [r.prob for r in result.runs if r.prob is not None]
    result.n_valid = len(valid)
    result.ensemble_prob = sum(valid) / len(valid) if valid else None
    return result
