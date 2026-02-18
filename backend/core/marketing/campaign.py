"""Campaign planner — manages marketing campaigns, budgets, and calendars.

A campaign groups related content items, tracks budget allocation and
spend, defines goals, and provides a timeline. Campaigns progress
through states:

    PLANNING → ACTIVE → PAUSED → COMPLETED
                 |
              CANCELLED

The campaign manager coordinates with the content workflow to aggregate
metrics across all content items belonging to a campaign.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

logger = logging.getLogger("nexus.marketing.campaign")


class CampaignStatus(str, Enum):
    """Campaign lifecycle states."""
    PLANNING = "planning"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CampaignType(str, Enum):
    """Types of marketing campaigns."""
    SOCIAL = "social"
    EMAIL = "email"
    ADS = "ads"
    SEO = "seo"
    MULTI_CHANNEL = "multi_channel"
    PROMOTION = "promotion"
    LAUNCH = "launch"
    SEASONAL = "seasonal"


# Valid campaign transitions
_CAMPAIGN_TRANSITIONS: dict[CampaignStatus, set[CampaignStatus]] = {
    CampaignStatus.PLANNING: {CampaignStatus.ACTIVE, CampaignStatus.CANCELLED},
    CampaignStatus.ACTIVE: {CampaignStatus.PAUSED, CampaignStatus.COMPLETED, CampaignStatus.CANCELLED},
    CampaignStatus.PAUSED: {CampaignStatus.ACTIVE, CampaignStatus.CANCELLED, CampaignStatus.COMPLETED},
    CampaignStatus.COMPLETED: set(),  # terminal
    CampaignStatus.CANCELLED: set(),  # terminal
}


@dataclass
class Campaign:
    """A marketing campaign with budget, timeline, and goals."""

    id: Optional[str] = None
    name: str = ""
    status: str = CampaignStatus.PLANNING.value
    campaign_type: str = CampaignType.MULTI_CHANNEL.value
    budget_usd: float = 0.0
    spent_usd: float = 0.0
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    goals: dict = field(default_factory=dict)    # {"impressions": 10000, "conversions": 50}
    strategy: str = ""                            # LLM-generated campaign strategy text
    brand_profile_id: Optional[int] = None
    org_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "campaign_type": self.campaign_type,
            "budget_usd": float(self.budget_usd) if self.budget_usd else 0.0,
            "spent_usd": float(self.spent_usd) if self.spent_usd else 0.0,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "goals": self.goals,
            "strategy": self.strategy,
            "brand_profile_id": self.brand_profile_id,
            "org_id": self.org_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Campaign:
        start = data.get("start_date")
        end = data.get("end_date")
        if isinstance(start, str):
            start = date.fromisoformat(start)
        if isinstance(end, str):
            end = date.fromisoformat(end)

        return cls(
            id=data.get("id"),
            name=data.get("name", ""),
            status=data.get("status", CampaignStatus.PLANNING.value),
            campaign_type=data.get("campaign_type", CampaignType.MULTI_CHANNEL.value),
            budget_usd=float(data.get("budget_usd") or 0),
            spent_usd=float(data.get("spent_usd") or 0),
            start_date=start,
            end_date=end,
            goals=data.get("goals") or {},
            strategy=data.get("strategy", ""),
            brand_profile_id=data.get("brand_profile_id"),
            org_id=data.get("org_id"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    @property
    def budget_remaining(self) -> float:
        return max(0, self.budget_usd - self.spent_usd)

    @property
    def budget_utilization(self) -> float:
        """Budget utilization as a percentage (0-100)."""
        if self.budget_usd <= 0:
            return 0.0
        return min(100.0, (self.spent_usd / self.budget_usd) * 100)

    @property
    def is_active(self) -> bool:
        return self.status == CampaignStatus.ACTIVE.value

    @property
    def is_terminal(self) -> bool:
        return self.status in (CampaignStatus.COMPLETED.value, CampaignStatus.CANCELLED.value)


class CampaignManager:
    """Manages marketing campaigns in PostgreSQL."""

    def __init__(self, db: Any):
        self.db = db

    async def create(self, data: dict) -> Campaign:
        """Create a new campaign in PLANNING state."""
        data["id"] = data.get("id") or str(uuid4())
        data["status"] = CampaignStatus.PLANNING.value

        row = await self.db.create_campaign(data)
        campaign = Campaign.from_dict(row)
        logger.info(
            f"Campaign created: {campaign.name} (id={campaign.id}, "
            f"type={campaign.campaign_type}, budget=${campaign.budget_usd:.2f})"
        )
        return campaign

    async def get(self, campaign_id: str) -> Optional[Campaign]:
        """Get a campaign by ID."""
        row = await self.db.get_campaign(campaign_id)
        if not row:
            return None
        return Campaign.from_dict(row)

    async def update(self, campaign_id: str, data: dict) -> Optional[Campaign]:
        """Update campaign fields (not status — use transition for that)."""
        row = await self.db.update_campaign(campaign_id, data)
        if not row:
            return None
        campaign = Campaign.from_dict(row)
        logger.info(f"Campaign updated: {campaign.name} (id={campaign.id})")
        return campaign

    async def transition(self, campaign_id: str, new_status: str) -> Campaign:
        """Transition a campaign to a new state."""
        row = await self.db.get_campaign(campaign_id)
        if not row:
            raise ValueError(f"Campaign not found: {campaign_id}")

        current = row.get("status", "")
        try:
            from_s = CampaignStatus(current)
            to_s = CampaignStatus(new_status)
        except ValueError:
            raise ValueError(f"Invalid status: {new_status}")

        if to_s not in _CAMPAIGN_TRANSITIONS.get(from_s, set()):
            raise ValueError(
                f"Invalid campaign transition: {current} → {new_status} "
                f"for campaign {campaign_id}"
            )

        updated = await self.db.update_campaign(campaign_id, {"status": new_status})
        campaign = Campaign.from_dict(updated)
        logger.info(f"Campaign transition: {campaign_id} {current} → {new_status}")
        return campaign

    async def activate(self, campaign_id: str) -> Campaign:
        """Activate a campaign (PLANNING → ACTIVE)."""
        return await self.transition(campaign_id, CampaignStatus.ACTIVE.value)

    async def pause(self, campaign_id: str) -> Campaign:
        """Pause a campaign."""
        return await self.transition(campaign_id, CampaignStatus.PAUSED.value)

    async def complete(self, campaign_id: str) -> Campaign:
        """Mark a campaign as completed."""
        return await self.transition(campaign_id, CampaignStatus.COMPLETED.value)

    async def cancel(self, campaign_id: str) -> Campaign:
        """Cancel a campaign."""
        return await self.transition(campaign_id, CampaignStatus.CANCELLED.value)

    async def record_spend(self, campaign_id: str, amount_usd: float) -> Campaign:
        """Record spend against a campaign's budget."""
        campaign = await self.get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign not found: {campaign_id}")

        new_spent = campaign.spent_usd + amount_usd
        updated = await self.db.update_campaign(
            campaign_id, {"spent_usd": new_spent}
        )
        campaign = Campaign.from_dict(updated)

        if campaign.budget_utilization >= 90:
            logger.warning(
                f"Campaign budget alert: {campaign.name} at "
                f"{campaign.budget_utilization:.1f}% "
                f"(${campaign.spent_usd:.2f}/${campaign.budget_usd:.2f})"
            )

        return campaign

    async def list_campaigns(
        self,
        *,
        status: str = None,
        campaign_type: str = None,
        org_id: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Campaign]:
        """List campaigns with optional filters."""
        rows = await self.db.list_campaigns(
            status=status,
            campaign_type=campaign_type,
            org_id=org_id,
            limit=limit,
            offset=offset,
        )
        return [Campaign.from_dict(r) for r in rows]

    async def archive(self, campaign_id: str) -> bool:
        """Soft-delete a campaign (sets status to cancelled)."""
        try:
            await self.cancel(campaign_id)
            return True
        except ValueError:
            # Already terminal — just return True
            return True

    async def get_summary(self, campaign_id: str) -> dict:
        """Get a campaign summary with content item counts and spend."""
        campaign = await self.get(campaign_id)
        if not campaign:
            return {}

        content_counts = await self.db.get_campaign_content_counts(campaign_id)

        return {
            **campaign.to_dict(),
            "content_counts": content_counts,
            "budget_remaining": campaign.budget_remaining,
            "budget_utilization": campaign.budget_utilization,
        }
