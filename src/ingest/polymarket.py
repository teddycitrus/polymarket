"""Polymarket data ingestion.

Reads live and resolved markets from the public Gamma API. No auth needed for
reads. We deliberately use only the stdlib (urllib) here so ingestion runs with
zero pip install; heavier deps live in the forecast layer.

Gamma API:  https://gamma-api.polymarket.com
Docs:       https://docs.polymarket.com
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterator

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
USER_AGENT = "polymarket-forecaster/0.1 (research; paper-trading only)"

# Cap upstream response bodies so a compromised/misbehaving API can't exhaust
# memory. Gamma/CLOB payloads are small; this is generous headroom.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

# Identifier whitelists. Gamma market ids are numeric and slugs/token ids use a
# constrained charset; validating before interpolating into a URL prevents path
# traversal and request-splitting (SSRF) via crafted identifiers.
_MARKET_ID_RE = re.compile(r"^[0-9]{1,32}$")
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,191})$")
_TOKEN_ID_RE = re.compile(r"^[0-9]{1,80}$")


@dataclass
class Market:
    """A single binary market, normalized to what the forecaster needs."""

    id: str
    question: str
    description: str
    slug: str
    end_date: str | None
    closed: bool
    volume: float
    # Crowd-implied probabilities. outcomes[i] corresponds to prices[i].
    outcomes: list[str] = field(default_factory=list)
    prices: list[float] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    # CLOB ERC1155 token IDs, aligned with `outcomes` (index 0 == outcomes[0]).
    clob_token_ids: list[str] = field(default_factory=list)
    # UMA oracle resolution status, e.g. "resolved". Empty if still open.
    uma_status: str = ""
    # Parent event, if fetched via the events endpoint. Gives the forecaster
    # broader context (e.g. event "Democratic Presidential Nominee 2028").
    event_title: str = ""
    # Parent event slug. Polymarket pages live at /event/<event_slug>, NOT at
    # the per-market slug, so this is what links should point at.
    event_slug: str = ""

    @property
    def yes_price(self) -> float | None:
        """Crowd probability of YES, if this is a Yes/No market."""
        for outcome, price in zip(self.outcomes, self.prices):
            if outcome.strip().lower() == "yes":
                return price
        return None

    @property
    def yes_token_id(self) -> str | None:
        """CLOB token ID for the YES outcome, used to pull the live price."""
        for outcome, token in zip(self.outcomes, self.clob_token_ids):
            if outcome.strip().lower() == "yes":
                return token
        return None

    @property
    def is_binary_yes_no(self) -> bool:
        labels = {o.strip().lower() for o in self.outcomes}
        return labels == {"yes", "no"}


def _read_json(resp: Any) -> Any:
    # Read at most MAX_RESPONSE_BYTES + 1 so we can detect (and reject) an
    # oversized body rather than buffering it unbounded.
    raw = resp.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("upstream response exceeds size limit")
    return json.loads(raw.decode("utf-8"))


def _get(path: str, params: dict[str, Any]) -> Any:
    query = urllib.parse.urlencode(params, doseq=True)
    url = f"{GAMMA_BASE}{path}?{query}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return _read_json(resp)


def _parse_json_list(raw: Any) -> list:
    """Gamma returns some array fields as JSON-encoded strings."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _to_market(raw: dict, *, event_title: str = "", event_slug: str = "") -> Market:
    prices = [float(p) for p in _parse_json_list(raw.get("outcomePrices"))]
    tags = [t.get("label", "") if isinstance(t, dict) else str(t) for t in _parse_json_list(raw.get("tags"))]
    # When fetched as a standalone market, the parent event (with its slug) is
    # nested under "events"; prefer an explicitly passed slug from the caller.
    if not event_slug:
        events = raw.get("events") or []
        if events and isinstance(events[0], dict):
            event_slug = events[0].get("slug", "") or ""
            event_title = event_title or events[0].get("title", "") or ""
    return Market(
        id=str(raw.get("id", "")),
        question=raw.get("question", ""),
        description=raw.get("description", "") or "",
        slug=raw.get("slug", ""),
        end_date=raw.get("endDate"),
        closed=bool(raw.get("closed", False)),
        volume=float(raw.get("volume") or 0.0),
        outcomes=_parse_json_list(raw.get("outcomes")),
        prices=prices,
        tags=tags,
        clob_token_ids=[str(t) for t in _parse_json_list(raw.get("clobTokenIds"))],
        uma_status=str(raw.get("umaResolutionStatus") or ""),
        event_title=event_title,
        event_slug=event_slug,
    )


def fetch_markets(
    *,
    closed: bool = False,
    limit: int = 50,
    tag: str | None = None,
    order: str = "volume",
    ascending: bool = False,
) -> list[Market]:
    """Fetch markets, most-traded first by default.

    tag: Gamma tag slug to filter by, e.g. "politics", "elections".
    """
    params: dict[str, Any] = {
        "closed": str(closed).lower(),
        "limit": limit,
        "order": order,
        "ascending": str(ascending).lower(),
    }
    if tag:
        params["tag_slug"] = tag
    raw = _get("/markets", params)
    return [_to_market(m) for m in raw]


def fetch_events(
    *,
    tag: str,
    closed: bool = False,
    limit: int = 50,
    order: str = "volume",
    ascending: bool = False,
) -> list[dict]:
    """Fetch events (groups of related markets) for a tag slug.

    Unlike /markets, the /events endpoint honors tag_slug, so this is the
    reliable way to filter by category.
    """
    params: dict[str, Any] = {
        "closed": str(closed).lower(),
        "limit": limit,
        "order": order,
        "ascending": str(ascending).lower(),
        "tag_slug": tag,
    }
    return _get("/events", params)


def fetch_political_markets(
    *,
    closed: bool = False,
    limit: int = 50,
    min_volume: float = 0.0,
    tag: str = "politics",
) -> list[Market]:
    """Open binary political markets, highest volume first.

    Pulls via the /events endpoint (which honors tag_slug), flattens the nested
    markets, keeps clean Yes/No markets, and dedupes. Each market carries its
    parent event title for forecaster context.
    """
    seen: dict[str, Market] = {}
    # Pull a generous number of events; each can contain many markets.
    events = fetch_events(tag=tag, closed=closed, limit=max(limit, 100))
    for event in events:
        title = event.get("title", "")
        slug = event.get("slug", "")
        for raw in event.get("markets", []):
            if raw.get("closed") is True and not closed:
                continue
            m = _to_market(raw, event_title=title, event_slug=slug)
            if m.id and m.is_binary_yes_no and m.volume >= min_volume:
                seen[m.id] = m

    markets = list(seen.values())
    markets.sort(key=lambda m: m.volume, reverse=True)
    return markets[:limit]


def fetch_market_by_slug(slug: str) -> Market | None:
    """Fetch a single market by its slug. Returns None if not found or invalid."""
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        return None
    raw = _get("/markets", {"slug": slug, "limit": 1})
    if not raw:
        return None
    return _to_market(raw[0])


def fetch_market_by_id(market_id: str) -> Market | None:
    """Fetch a single market by its Gamma id, including closed/resolved ones.

    Uses the direct /markets/<id> path, which (unlike the filtered list query)
    returns the market regardless of closed status -- essential for resolution.
    The id is validated as numeric before interpolation to prevent path
    traversal / request-splitting into the upstream URL.
    """
    if not isinstance(market_id, str) or not _MARKET_ID_RE.match(market_id):
        return None
    try:
        raw = _get(f"/markets/{urllib.parse.quote(market_id, safe='')}", {})
    except urllib.error.HTTPError:
        return None
    if not isinstance(raw, dict) or not raw:
        return None
    return _to_market(raw)


def resolved_outcome(market: Market) -> float | None:
    """Definitive binary outcome of a resolved market.

    Returns 1.0 if YES won, 0.0 if NO won, or None if the market is not yet
    settled (still open, or closed without a clean resolution). A resolved
    binary market reports outcomePrices of [1, 0] or [0, 1].
    """
    if not market.closed:
        return None
    if market.uma_status and market.uma_status.lower() != "resolved":
        return None
    yp = market.yes_price
    if yp is None:
        return None
    if yp >= 0.99:
        return 1.0
    if yp <= 0.01:
        return 0.0
    return None  # closed but ambiguous (e.g. cancelled / 50-50)


def _clob_get(path: str, params: dict[str, Any]) -> Any:
    query = urllib.parse.urlencode(params, doseq=True)
    url = f"{CLOB_BASE}{path}?{query}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return _read_json(resp)


def fetch_clob_midpoint(token_id: str) -> float | None:
    """Live midpoint price (best bid/ask average) for a CLOB token.

    This is the real-time crowd probability, fresher than the Gamma snapshot.
    """
    if not isinstance(token_id, str) or not _TOKEN_ID_RE.match(token_id):
        return None
    try:
        data = _clob_get("/midpoint", {"token_id": token_id})
    except urllib.error.HTTPError:
        return None
    mid = data.get("mid")
    return float(mid) if mid is not None else None


def fetch_clob_book(token_id: str) -> dict | None:
    """Full order book for a CLOB token: {'bids': [...], 'asks': [...]}."""
    if not isinstance(token_id, str) or not _TOKEN_ID_RE.match(token_id):
        return None
    try:
        return _clob_get("/book", {"token_id": token_id})
    except urllib.error.HTTPError:
        return None


def live_yes_price(market: Market) -> float | None:
    """Best available live YES probability: CLOB midpoint, else Gamma snapshot."""
    token = market.yes_token_id
    if token:
        mid = fetch_clob_midpoint(token)
        if mid is not None:
            return mid
    return market.yes_price


def iter_market_summaries(markets: list[Market]) -> Iterator[str]:
    for m in markets:
        yes = m.yes_price
        yes_str = f"{yes:.2f}" if yes is not None else "  ?"
        yield f"[{yes_str}] vol={m.volume:>10,.0f}  {m.question[:80]}"
