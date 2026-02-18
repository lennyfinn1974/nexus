"""Multi-touch attribution and UTM builder.

Provides 5 attribution models for understanding which marketing
touchpoints drive conversions:

1. Last Touch — 100% credit to last interaction before conversion
2. First Touch — 100% credit to first interaction
3. Linear — Equal credit to all touchpoints
4. Time Decay — More credit to recent touchpoints (half-life decay)
5. Position-Based (U-shaped) — 40% first, 40% last, 20% split middle

Also provides a UTM parameter builder for tracking marketing links.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

logger = logging.getLogger("nexus.marketing.attribution")


class AttributionModel(str, Enum):
    """Available attribution models."""
    LAST_TOUCH = "last_touch"
    FIRST_TOUCH = "first_touch"
    LINEAR = "linear"
    TIME_DECAY = "time_decay"
    POSITION_BASED = "position_based"


@dataclass
class Touchpoint:
    """A single marketing touchpoint in a customer journey."""
    channel: str          # "social", "email", "ads", "organic", "direct", "referral"
    source: str           # "instagram", "google_ads", "mailchimp", etc.
    campaign_id: str = ""
    content_id: str = ""
    timestamp: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "source": self.source,
            "campaign_id": self.campaign_id,
            "content_id": self.content_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "metadata": self.metadata,
        }


@dataclass
class AttributionResult:
    """Attribution credit assignment for touchpoints."""
    touchpoints: list[Touchpoint]
    credits: dict[int, float]  # touchpoint_index → credit (0.0 to 1.0)
    model: str
    conversion_value: float = 0.0

    def to_dict(self) -> dict:
        result = []
        for idx, tp in enumerate(self.touchpoints):
            result.append({
                **tp.to_dict(),
                "credit": self.credits.get(idx, 0.0),
                "attributed_value": self.credits.get(idx, 0.0) * self.conversion_value,
            })
        return {
            "model": self.model,
            "conversion_value": self.conversion_value,
            "touchpoints": result,
        }


def attribute(
    touchpoints: list[Touchpoint],
    model: str = AttributionModel.POSITION_BASED.value,
    conversion_value: float = 1.0,
    half_life_days: float = 7.0,
) -> AttributionResult:
    """Apply an attribution model to a list of touchpoints.

    Args:
        touchpoints: Ordered list of touchpoints (earliest first)
        model: Attribution model to use
        conversion_value: Total value to attribute (e.g. revenue)
        half_life_days: For time_decay model, the half-life in days

    Returns:
        AttributionResult with credit assignments
    """
    n = len(touchpoints)
    if n == 0:
        return AttributionResult([], {}, model, conversion_value)

    credits: dict[int, float] = {}

    if model == AttributionModel.LAST_TOUCH.value:
        credits = {i: 0.0 for i in range(n)}
        credits[n - 1] = 1.0

    elif model == AttributionModel.FIRST_TOUCH.value:
        credits = {i: 0.0 for i in range(n)}
        credits[0] = 1.0

    elif model == AttributionModel.LINEAR.value:
        share = 1.0 / n
        credits = {i: share for i in range(n)}

    elif model == AttributionModel.TIME_DECAY.value:
        # Exponential decay from last touchpoint
        if n == 1:
            credits = {0: 1.0}
        else:
            last_ts = touchpoints[-1].timestamp or datetime.utcnow()
            raw = {}
            for i, tp in enumerate(touchpoints):
                ts = tp.timestamp or datetime.utcnow()
                days_before = (last_ts - ts).total_seconds() / 86400
                raw[i] = math.pow(0.5, days_before / half_life_days)
            total = sum(raw.values())
            credits = {i: v / total for i, v in raw.items()} if total > 0 else {i: 1.0 / n for i in range(n)}

    elif model == AttributionModel.POSITION_BASED.value:
        # U-shaped: 40% first, 40% last, 20% split among middle
        if n == 1:
            credits = {0: 1.0}
        elif n == 2:
            credits = {0: 0.5, 1: 0.5}
        else:
            credits = {i: 0.0 for i in range(n)}
            credits[0] = 0.4
            credits[n - 1] = 0.4
            middle_share = 0.2 / (n - 2) if n > 2 else 0
            for i in range(1, n - 1):
                credits[i] = middle_share

    else:
        # Default to linear
        share = 1.0 / n
        credits = {i: share for i in range(n)}

    return AttributionResult(
        touchpoints=touchpoints,
        credits=credits,
        model=model,
        conversion_value=conversion_value,
    )


# ── UTM Builder ──────────────────────────────────────────────────


def build_utm_url(
    base_url: str,
    *,
    source: str,
    medium: str,
    campaign: str,
    content: str = "",
    term: str = "",
) -> str:
    """Build a URL with UTM tracking parameters.

    Args:
        base_url: The destination URL
        source: Traffic source (e.g. "instagram", "google", "newsletter")
        medium: Marketing medium (e.g. "social", "cpc", "email")
        campaign: Campaign name/ID
        content: Content identifier (for A/B testing)
        term: Keyword term (for paid search)

    Returns:
        URL with UTM parameters appended
    """
    params = {
        "utm_source": source,
        "utm_medium": medium,
        "utm_campaign": campaign,
    }
    if content:
        params["utm_content"] = content
    if term:
        params["utm_term"] = term

    # Parse existing URL and merge params
    parsed = urlparse(base_url)
    existing_params = parse_qs(parsed.query)

    # Merge — UTM params override existing
    for k, v in params.items():
        existing_params[k] = [v]

    # Rebuild query string
    flat = {k: v[0] if isinstance(v, list) else v for k, v in existing_params.items()}
    new_query = urlencode(flat)

    return urlunparse((
        parsed.scheme or "https",
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment,
    ))


def parse_utm_params(url: str) -> dict:
    """Extract UTM parameters from a URL.

    Returns a dict with keys: source, medium, campaign, content, term.
    Missing parameters are empty strings.
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    return {
        "source": params.get("utm_source", [""])[0],
        "medium": params.get("utm_medium", [""])[0],
        "campaign": params.get("utm_campaign", [""])[0],
        "content": params.get("utm_content", [""])[0],
        "term": params.get("utm_term", [""])[0],
    }
