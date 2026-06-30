"""News retrieval via Claude's web search.

Gathers a handful of recent, dated news items relevant to a market topic. We
fetch once (not per ensemble run) so all forecast runs reason over the same
evidence, which makes the ensemble cheaper and the spread more meaningful.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from llm import LLMError, call_claude


@dataclass
class NewsItem:
    date: str
    headline: str
    source: str
    summary: str

    def as_line(self) -> str:
        return f"[{self.date}] {self.headline} ({self.source}) - {self.summary}"


_PROMPT = """You are a research assistant gathering recent, factual news for a forecasting task.

Use web search to find the {max_items} most recent and relevant news items about:
{topic}

Requirements:
- Only include items you actually found via search, each with a real publication date.
- Prefer the most recent items; order from newest to oldest.
- Focus on facts that bear on how the question will resolve.

Return ONLY a JSON array, no prose and no markdown code fences. Each element:
{{"date": "YYYY-MM-DD", "headline": "...", "source": "...", "summary": "one factual sentence"}}
"""


def _extract_json_array(raw: str) -> list:
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end <= start:
        raise LLMError(f"no JSON array found in news output: {raw[:200]!r}")
    return json.loads(raw[start : end + 1])


def fetch_news(topic: str, *, max_items: int = 5, timeout: int = 480) -> list[NewsItem]:
    prompt = _PROMPT.format(topic=topic, max_items=max_items)
    try:
        raw = call_claude(prompt, allowed_tools=["WebSearch"], timeout=timeout)
        items = _extract_json_array(raw)
    except (json.JSONDecodeError, LLMError):
        # Degrade gracefully: a forecast with no news is still valid, just
        # weaker, and a slow/failed search shouldn't kill the whole run.
        return []
    out: list[NewsItem] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append(
            NewsItem(
                date=str(it.get("date", "")).strip(),
                headline=str(it.get("headline", "")).strip(),
                source=str(it.get("source", "")).strip(),
                summary=str(it.get("summary", "")).strip(),
            )
        )
    return out[:max_items]
