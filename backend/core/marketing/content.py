"""Content workflow state machine — manages content lifecycle.

Content items (social posts, emails, ad copy, blog posts) progress
through a state machine:

    DRAFT → REVIEW → APPROVED → SCHEDULED → PUBLISHED
      ↑        |                                 |
      |   (rejected)                          (failed)
      +--------+                                 |
                                                 v
                                              FAILED

Key design decisions:
- Content is NEVER auto-published without explicit human approval
- The agent creates drafts; humans approve and schedule
- Failed publishes can be retried (transitions back to APPROVED)
- All state transitions are logged for audit trail
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

logger = logging.getLogger("nexus.marketing.content")


class ContentStatus(str, Enum):
    """Content workflow states."""
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"
    ARCHIVED = "archived"


class ContentType(str, Enum):
    """Types of marketing content."""
    SOCIAL_POST = "social_post"
    EMAIL = "email"
    AD_COPY = "ad_copy"
    BLOG_POST = "blog_post"
    NEWSLETTER = "newsletter"
    SMS_BLAST = "sms_blast"
    WHATSAPP_TEMPLATE = "whatsapp_template"


# Valid state transitions
_TRANSITIONS: dict[ContentStatus, set[ContentStatus]] = {
    ContentStatus.DRAFT: {ContentStatus.REVIEW, ContentStatus.ARCHIVED},
    ContentStatus.REVIEW: {ContentStatus.APPROVED, ContentStatus.DRAFT},  # reject → back to draft
    ContentStatus.APPROVED: {ContentStatus.SCHEDULED, ContentStatus.PUBLISHED, ContentStatus.ARCHIVED},
    ContentStatus.SCHEDULED: {ContentStatus.PUBLISHED, ContentStatus.FAILED, ContentStatus.APPROVED},  # unschedule → approved
    ContentStatus.PUBLISHED: {ContentStatus.ARCHIVED},
    ContentStatus.FAILED: {ContentStatus.APPROVED, ContentStatus.ARCHIVED},  # retry → approved
    ContentStatus.ARCHIVED: set(),  # terminal state
}


@dataclass
class ContentItem:
    """A piece of marketing content progressing through the workflow."""

    id: Optional[str] = None
    campaign_id: Optional[str] = None
    content_type: str = ContentType.SOCIAL_POST.value
    platform: str = ""               # instagram, facebook, linkedin, twitter, email, etc.
    status: str = ContentStatus.DRAFT.value
    title: str = ""
    body: str = ""
    media_urls: list = field(default_factory=list)
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    external_id: str = ""            # Post ID from platform after publishing
    metrics: dict = field(default_factory=dict)
    brand_profile_id: Optional[int] = None
    created_by: str = ""             # "agent" or user ID
    approved_by: str = ""
    org_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "campaign_id": self.campaign_id,
            "content_type": self.content_type,
            "platform": self.platform,
            "status": self.status,
            "title": self.title,
            "body": self.body,
            "media_urls": self.media_urls,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "external_id": self.external_id,
            "metrics": self.metrics,
            "brand_profile_id": self.brand_profile_id,
            "created_by": self.created_by,
            "approved_by": self.approved_by,
            "org_id": self.org_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ContentItem:
        return cls(
            id=data.get("id"),
            campaign_id=data.get("campaign_id"),
            content_type=data.get("content_type", ContentType.SOCIAL_POST.value),
            platform=data.get("platform", ""),
            status=data.get("status", ContentStatus.DRAFT.value),
            title=data.get("title", ""),
            body=data.get("body", ""),
            media_urls=data.get("media_urls") or [],
            scheduled_at=data.get("scheduled_at"),
            published_at=data.get("published_at"),
            external_id=data.get("external_id", ""),
            metrics=data.get("metrics") or {},
            brand_profile_id=data.get("brand_profile_id"),
            created_by=data.get("created_by", ""),
            approved_by=data.get("approved_by", ""),
            org_id=data.get("org_id"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class ContentWorkflow:
    """Manages content lifecycle through the state machine.

    All state transitions are validated and persisted to PostgreSQL.
    Invalid transitions raise ValueError.
    """

    def __init__(self, db: Any):
        self.db = db

    def can_transition(self, from_status: str, to_status: str) -> bool:
        """Check if a state transition is valid."""
        try:
            from_s = ContentStatus(from_status)
            to_s = ContentStatus(to_status)
        except ValueError:
            return False
        return to_s in _TRANSITIONS.get(from_s, set())

    async def create(self, data: dict) -> ContentItem:
        """Create a new content item in DRAFT state."""
        data["id"] = data.get("id") or str(uuid4())
        data["status"] = ContentStatus.DRAFT.value
        data["created_by"] = data.get("created_by", "agent")

        row = await self.db.create_content_item(data)
        item = ContentItem.from_dict(row)
        logger.info(
            f"Content created: {item.id} type={item.content_type} "
            f"platform={item.platform} by={item.created_by}"
        )
        return item

    async def transition(
        self,
        content_id: str,
        new_status: str,
        *,
        approved_by: str = "",
        scheduled_at: Optional[datetime] = None,
        external_id: str = "",
        published_at: Optional[datetime] = None,
        metrics: Optional[dict] = None,
    ) -> ContentItem:
        """Transition a content item to a new state.

        Raises ValueError if the transition is invalid.
        """
        # Fetch current state
        row = await self.db.get_content_item(content_id)
        if not row:
            raise ValueError(f"Content item not found: {content_id}")

        current_status = row.get("status", "")
        if not self.can_transition(current_status, new_status):
            raise ValueError(
                f"Invalid transition: {current_status} → {new_status} "
                f"for content {content_id}"
            )

        # Build update data
        updates: dict[str, Any] = {"status": new_status}

        if new_status == ContentStatus.APPROVED.value and approved_by:
            updates["approved_by"] = approved_by

        if new_status == ContentStatus.SCHEDULED.value and scheduled_at:
            updates["scheduled_at"] = scheduled_at

        if new_status == ContentStatus.PUBLISHED.value:
            updates["published_at"] = published_at or datetime.utcnow()
            if external_id:
                updates["external_id"] = external_id

        if metrics:
            updates["metrics"] = metrics

        updated = await self.db.update_content_item(content_id, updates)
        item = ContentItem.from_dict(updated)

        logger.info(
            f"Content transition: {content_id} "
            f"{current_status} → {new_status}"
        )
        return item

    async def submit_for_review(self, content_id: str) -> ContentItem:
        """Move content from DRAFT to REVIEW."""
        return await self.transition(content_id, ContentStatus.REVIEW.value)

    async def approve(self, content_id: str, approved_by: str = "admin") -> ContentItem:
        """Approve content (REVIEW → APPROVED)."""
        return await self.transition(
            content_id, ContentStatus.APPROVED.value, approved_by=approved_by
        )

    async def reject(self, content_id: str) -> ContentItem:
        """Reject content back to draft (REVIEW → DRAFT)."""
        return await self.transition(content_id, ContentStatus.DRAFT.value)

    async def schedule(self, content_id: str, publish_at: datetime) -> ContentItem:
        """Schedule approved content for publication."""
        return await self.transition(
            content_id, ContentStatus.SCHEDULED.value, scheduled_at=publish_at
        )

    async def mark_published(
        self,
        content_id: str,
        external_id: str = "",
        metrics: Optional[dict] = None,
    ) -> ContentItem:
        """Mark content as published (after platform confirms)."""
        return await self.transition(
            content_id,
            ContentStatus.PUBLISHED.value,
            external_id=external_id,
            metrics=metrics,
        )

    async def mark_failed(self, content_id: str) -> ContentItem:
        """Mark a publish attempt as failed."""
        return await self.transition(content_id, ContentStatus.FAILED.value)

    async def retry(self, content_id: str) -> ContentItem:
        """Retry a failed publish (FAILED → APPROVED)."""
        return await self.transition(content_id, ContentStatus.APPROVED.value)

    async def get_approval_queue(self, org_id: str = None) -> list[ContentItem]:
        """Get all content items waiting for approval."""
        rows = await self.db.list_content_items(
            status=ContentStatus.REVIEW.value, org_id=org_id
        )
        return [ContentItem.from_dict(r) for r in rows]

    async def get_scheduled(self, org_id: str = None) -> list[ContentItem]:
        """Get all scheduled content items (for the publisher to process)."""
        rows = await self.db.list_content_items(
            status=ContentStatus.SCHEDULED.value, org_id=org_id
        )
        return [ContentItem.from_dict(r) for r in rows]

    async def list_items(
        self,
        *,
        campaign_id: str = None,
        status: str = None,
        platform: str = None,
        content_type: str = None,
        org_id: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ContentItem]:
        """List content items with optional filters."""
        rows = await self.db.list_content_items(
            campaign_id=campaign_id,
            status=status,
            platform=platform,
            content_type=content_type,
            org_id=org_id,
            limit=limit,
            offset=offset,
        )
        return [ContentItem.from_dict(r) for r in rows]
