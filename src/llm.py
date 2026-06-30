"""Anthropic API client wrapper.

Routes inference through the official `anthropic` Python SDK using
ANTHROPIC_API_KEY. Replaces the earlier approach of shelling out to the local
`claude` CLI, so it runs unattended in a serverless function.

The public surface (`call_claude`) is unchanged from the CLI version, so the
news and forecast layers keep working without edits. `allowed_tools=["WebSearch"]`
maps to Anthropic's server-side web_search tool.
"""

from __future__ import annotations

import os

import anthropic

# Friendly aliases -> concrete API model ids, so callers can keep passing
# "sonnet" while we target the latest concrete model.
_MODEL_ALIASES = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-8",
    "haiku": "claude-haiku-4-5-20251001",
}
DEFAULT_MODEL = "sonnet"

# Server-side web search tool (Anthropic-hosted).
_WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


class LLMError(RuntimeError):
    """Raised when the Anthropic call fails or returns unusable output."""


_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError("ANTHROPIC_API_KEY is not set; the forecaster needs it to call the model.")
        _client = anthropic.Anthropic()
    return _client


def _resolve_model(model: str | None) -> str:
    # ANTHROPIC_MODEL env wins over everything, so if the default model id is
    # ever rejected by the API you can fix it without a code change/redeploy.
    env_model = os.environ.get("ANTHROPIC_MODEL")
    if env_model:
        return _MODEL_ALIASES.get(env_model, env_model)
    model = model or DEFAULT_MODEL
    return _MODEL_ALIASES.get(model, model)


def call_claude(
    prompt: str,
    *,
    allowed_tools: list[str] | None = None,
    model: str | None = DEFAULT_MODEL,
    timeout: int = 240,
    max_tokens: int = 4096,
) -> str:
    """Run one model turn and return its concatenated text output.

    allowed_tools: pass ["WebSearch"] to enable Anthropic's server-side web
    search. Omit for pure text generation.
    """
    client = _get_client()
    tools = [_WEB_SEARCH_TOOL] if allowed_tools and "WebSearch" in allowed_tools else []

    try:
        resp = client.messages.create(
            model=_resolve_model(model),
            max_tokens=max_tokens,
            tools=tools,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
        )
    except anthropic.APIError as e:
        raise LLMError(f"Anthropic API error: {e}") from e

    # Concatenate the assistant's text blocks (web_search results are handled
    # server-side and surface as additional text in the final answer).
    text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
    if not text.strip():
        raise LLMError(f"empty text response (stop_reason={resp.stop_reason})")
    return text
