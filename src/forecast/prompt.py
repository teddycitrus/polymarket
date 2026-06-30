"""The forecasting prompt: a strict 5-step decomposition.

Calibration research shows the biggest accuracy gain comes from forcing the
model to decompose the question and weigh both sides BEFORE committing to a
number, rather than from a bigger model. The prompt ends with machine-parseable
marker lines so we can extract the probability deterministically.
"""

from __future__ import annotations

SYSTEM_PREAMBLE = (
    "You are a calibrated superforecaster. You reason carefully, start from base "
    "rates, weigh evidence on both sides, and avoid overconfidence. You are NOT "
    "told the market price, so you cannot anchor to it."
)

_TEMPLATE = """{preamble}

Today's date: {today}

# Market question
{question}
{event_line}
# Exact resolution criteria
{resolution}

# Recent news (dated; treat skeptically and check dates against today)
{news_block}

# Your task — work through these FIVE steps explicitly, in order:

STEP 1 - RESTATE CRITERIA: In one or two sentences, restate precisely what must
happen for this market to resolve YES, and by when.

STEP 2 - DRIVERS & EVIDENCE: List the key factors that push toward YES and the
key factors that push toward NO. Be balanced.

STEP 3 - NEWS REASONING: Go through the relevant news items above. For each one
you use, note its date and whether it is still current given today's date.
Discount stale or superseded information.

STEP 4 - BASE RATES FIRST: State a reasonable base rate / outside view for an
event like this BEFORE adjusting. Then adjust up or down for the specific
evidence, explaining each adjustment.

STEP 5 - FINAL ESTIMATE: Commit to a single calibrated probability that the
market resolves YES.

# Output format
After your reasoning, end your response with EXACTLY these three lines and
nothing after them:
FINAL_PROBABILITY: <number between 0 and 1>
CONFIDENCE: <low|medium|high>
SUMMARY: <one sentence justifying the probability>
"""


def build_forecast_prompt(
    *,
    question: str,
    resolution: str,
    news_lines: list[str],
    today: str,
    event_title: str = "",
) -> str:
    news_block = "\n".join(f"- {line}" for line in news_lines) if news_lines else "(no relevant news found)"
    event_line = f"\n# Parent event\n{event_title}\n" if event_title else ""
    return _TEMPLATE.format(
        preamble=SYSTEM_PREAMBLE,
        today=today,
        question=question,
        event_line=event_line,
        resolution=resolution or "(no explicit resolution text provided)",
        news_block=news_block,
    )
