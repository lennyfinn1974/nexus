"""Marketing REST API — campaigns, content, brand profiles, calendar, analytics.

All endpoints require admin authentication. The Marketing UI panel and
the Nexus agent both consume this API.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("nexus.routers.marketing")

router = APIRouter(prefix="/api/marketing", tags=["marketing"])


def _get_state(request: Request) -> Any:
    return request.app.state.nexus


def _get_marketing(request: Request):
    """Get marketing managers from app state."""
    state = _get_state(request)
    return {
        "brand": getattr(state, "brand_voice_manager", None),
        "content": getattr(state, "content_workflow", None),
        "campaign": getattr(state, "campaign_manager", None),
        "db": state.db,
    }


# ── Brand Profiles ────────────────────────────────────────────────


@router.get("/brand-profiles")
async def list_brand_profiles(request: Request):
    """List all brand voice profiles."""
    mkt = _get_marketing(request)
    brand = mkt["brand"]
    if not brand:
        return {"profiles": [], "total": 0}

    profiles = [p.to_dict() for p in brand._cache.values()]
    return {"profiles": profiles, "total": len(profiles)}


@router.post("/brand-profiles")
async def create_brand_profile(request: Request):
    """Create a new brand voice profile.

    Body: {
        "name": "My Cafe Brand",
        "tone": "warm, friendly, knowledgeable about coffee",
        "vocabulary_rules": {"preferred": ["artisan", "handcrafted"], "banned": ["cheap"]},
        "examples": [{"platform": "instagram", "text": "..."}],
        "platform_guidelines": {"instagram": "Use emojis...", "email": "More formal..."},
        "is_default": true
    }
    """
    mkt = _get_marketing(request)
    brand = mkt["brand"]
    if not brand:
        raise HTTPException(status_code=503, detail="Marketing system not initialized")

    body = await request.json()
    if not body.get("name"):
        raise HTTPException(status_code=400, detail="Brand profile name is required")

    profile = await brand.create(body)
    return {"status": "created", "profile": profile.to_dict()}


@router.put("/brand-profiles/{profile_id}")
async def update_brand_profile(profile_id: int, request: Request):
    """Update a brand voice profile."""
    mkt = _get_marketing(request)
    brand = mkt["brand"]
    if not brand:
        raise HTTPException(status_code=503, detail="Marketing system not initialized")

    body = await request.json()
    profile = await brand.update(profile_id, body)
    if not profile:
        raise HTTPException(status_code=404, detail="Brand profile not found")

    return {"status": "updated", "profile": profile.to_dict()}


@router.delete("/brand-profiles/{profile_id}")
async def delete_brand_profile(profile_id: int, request: Request):
    """Delete a brand voice profile."""
    mkt = _get_marketing(request)
    brand = mkt["brand"]
    if not brand:
        raise HTTPException(status_code=503, detail="Marketing system not initialized")

    deleted = await brand.delete(profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Brand profile not found")

    return {"status": "deleted", "id": profile_id}


# ── Campaigns ─────────────────────────────────────────────────────


@router.get("/campaigns")
async def list_campaigns(
    request: Request,
    status: str = None,
    campaign_type: str = None,
    limit: int = 50,
    offset: int = 0,
):
    """List marketing campaigns with optional filters."""
    mkt = _get_marketing(request)
    mgr = mkt["campaign"]
    if not mgr:
        return {"campaigns": [], "total": 0}

    campaigns = await mgr.list_campaigns(
        status=status, campaign_type=campaign_type, limit=limit, offset=offset
    )
    return {
        "campaigns": [c.to_dict() for c in campaigns],
        "total": len(campaigns),
    }


@router.post("/campaigns")
async def create_campaign(request: Request):
    """Create a new marketing campaign.

    Body: {
        "name": "Spring Coffee Launch",
        "campaign_type": "multi_channel",
        "budget_usd": 500.00,
        "start_date": "2026-03-01",
        "end_date": "2026-03-31",
        "goals": {"impressions": 10000, "conversions": 50},
        "strategy": "Focus on Instagram and email...",
        "brand_profile_id": 1
    }
    """
    mkt = _get_marketing(request)
    mgr = mkt["campaign"]
    if not mgr:
        raise HTTPException(status_code=503, detail="Marketing system not initialized")

    body = await request.json()
    if not body.get("name"):
        raise HTTPException(status_code=400, detail="Campaign name is required")

    campaign = await mgr.create(body)
    return {"status": "created", "campaign": campaign.to_dict()}


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str, request: Request):
    """Get campaign detail with content item counts."""
    mkt = _get_marketing(request)
    mgr = mkt["campaign"]
    if not mgr:
        raise HTTPException(status_code=503, detail="Marketing system not initialized")

    summary = await mgr.get_summary(campaign_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return {"campaign": summary}


@router.put("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: str, request: Request):
    """Update campaign fields."""
    mkt = _get_marketing(request)
    mgr = mkt["campaign"]
    if not mgr:
        raise HTTPException(status_code=503, detail="Marketing system not initialized")

    body = await request.json()

    # Handle status transitions separately
    if "status" in body and len(body) == 1:
        try:
            campaign = await mgr.transition(campaign_id, body["status"])
            return {"status": "transitioned", "campaign": campaign.to_dict()}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    campaign = await mgr.update(campaign_id, body)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return {"status": "updated", "campaign": campaign.to_dict()}


@router.delete("/campaigns/{campaign_id}")
async def archive_campaign(campaign_id: str, request: Request):
    """Archive (soft delete) a campaign."""
    mkt = _get_marketing(request)
    mgr = mkt["campaign"]
    if not mgr:
        raise HTTPException(status_code=503, detail="Marketing system not initialized")

    await mgr.archive(campaign_id)
    return {"status": "archived", "id": campaign_id}


# ── Content Items ─────────────────────────────────────────────────


@router.get("/content")
async def list_content(
    request: Request,
    campaign_id: str = None,
    status: str = None,
    platform: str = None,
    content_type: str = None,
    limit: int = 50,
    offset: int = 0,
):
    """List content items with optional filters."""
    mkt = _get_marketing(request)
    workflow = mkt["content"]
    if not workflow:
        return {"items": [], "total": 0}

    items = await workflow.list_items(
        campaign_id=campaign_id,
        status=status,
        platform=platform,
        content_type=content_type,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [i.to_dict() for i in items],
        "total": len(items),
    }


@router.post("/content")
async def create_content(request: Request):
    """Create a new content item in DRAFT state.

    Body: {
        "campaign_id": "uuid",
        "content_type": "social_post",
        "platform": "instagram",
        "title": "Spring Coffee Launch Post",
        "body": "Introducing our new spring blend...",
        "media_urls": ["https://..."],
        "brand_profile_id": 1
    }
    """
    mkt = _get_marketing(request)
    workflow = mkt["content"]
    if not workflow:
        raise HTTPException(status_code=503, detail="Marketing system not initialized")

    body = await request.json()
    item = await workflow.create(body)
    return {"status": "created", "item": item.to_dict()}


@router.put("/content/{content_id}")
async def update_content(content_id: str, request: Request):
    """Update a content item (edit body, title, media, etc.)."""
    mkt = _get_marketing(request)
    db = mkt["db"]
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")

    body = await request.json()
    updated = await db.update_content_item(content_id, body)
    if not updated:
        raise HTTPException(status_code=404, detail="Content item not found")

    from core.marketing.content import ContentItem
    return {"status": "updated", "item": ContentItem.from_dict(updated).to_dict()}


@router.post("/content/{content_id}/approve")
async def approve_content(content_id: str, request: Request):
    """Approve a content item for scheduling (REVIEW → APPROVED)."""
    mkt = _get_marketing(request)
    workflow = mkt["content"]
    if not workflow:
        raise HTTPException(status_code=503, detail="Marketing system not initialized")

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    approved_by = body.get("approved_by", "admin")

    try:
        item = await workflow.approve(content_id, approved_by=approved_by)
        return {"status": "approved", "item": item.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/content/{content_id}/reject")
async def reject_content(content_id: str, request: Request):
    """Reject content back to draft (REVIEW → DRAFT)."""
    mkt = _get_marketing(request)
    workflow = mkt["content"]
    if not workflow:
        raise HTTPException(status_code=503, detail="Marketing system not initialized")

    try:
        item = await workflow.reject(content_id)
        return {"status": "rejected", "item": item.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/content/{content_id}/schedule")
async def schedule_content(content_id: str, request: Request):
    """Schedule approved content for publication.

    Body: {"scheduled_at": "2026-03-15T09:00:00Z"}
    """
    mkt = _get_marketing(request)
    workflow = mkt["content"]
    if not workflow:
        raise HTTPException(status_code=503, detail="Marketing system not initialized")

    body = await request.json()
    scheduled_at = body.get("scheduled_at")
    if not scheduled_at:
        raise HTTPException(status_code=400, detail="scheduled_at is required")

    if isinstance(scheduled_at, str):
        scheduled_at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))

    try:
        item = await workflow.schedule(content_id, scheduled_at)
        return {"status": "scheduled", "item": item.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/content/{content_id}/publish")
async def publish_content(content_id: str, request: Request):
    """Publish a content item immediately (APPROVED → PUBLISHED).

    Body: {"external_id": "post_12345"} (optional — platform may return it async)
    """
    mkt = _get_marketing(request)
    workflow = mkt["content"]
    if not workflow:
        raise HTTPException(status_code=503, detail="Marketing system not initialized")

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}

    try:
        item = await workflow.mark_published(
            content_id,
            external_id=body.get("external_id", ""),
        )
        return {"status": "published", "item": item.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Approval Queue ────────────────────────────────────────────────


@router.get("/approval-queue")
async def approval_queue(request: Request):
    """Get all content items waiting for human approval."""
    mkt = _get_marketing(request)
    workflow = mkt["content"]
    if not workflow:
        return {"items": [], "total": 0}

    items = await workflow.get_approval_queue()
    return {
        "items": [i.to_dict() for i in items],
        "total": len(items),
    }


# ── Calendar ──────────────────────────────────────────────────────


@router.get("/calendar")
async def get_calendar(
    request: Request,
    start: str = None,
    end: str = None,
):
    """Get calendar events for a date range.

    Events include scheduled content publishes and campaign milestones.
    """
    mkt = _get_marketing(request)
    db = mkt["db"]
    if not db:
        return {"events": []}

    events = await db.get_calendar_events(start_date=start, end_date=end)
    return {"events": events}


@router.post("/calendar")
async def create_calendar_event(request: Request):
    """Create a calendar event.

    Body: {
        "campaign_id": "uuid",
        "content_item_id": "uuid",
        "event_type": "publish",
        "title": "Instagram post goes live",
        "scheduled_at": "2026-03-15T09:00:00Z"
    }
    """
    mkt = _get_marketing(request)
    db = mkt["db"]
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")

    body = await request.json()
    event = await db.create_calendar_event(body)
    return {"status": "created", "event": event}


# ── Analytics ─────────────────────────────────────────────────────


@router.get("/analytics")
async def marketing_analytics(
    request: Request,
    source: str = None,
    days: int = 30,
):
    """Get cross-channel marketing metrics.

    Aggregates metrics from social media, email, ads, and SEO.
    """
    mkt = _get_marketing(request)
    db = mkt["db"]
    if not db:
        return {"metrics": {}, "period_days": days}

    metrics = await db.get_marketing_metrics(source=source, days=days)
    return {"metrics": metrics, "period_days": days, "source": source}


@router.get("/analytics/{source}")
async def marketing_analytics_by_source(
    source: str,
    request: Request,
    days: int = 30,
):
    """Get metrics for a specific marketing source (social, email, ads, seo)."""
    mkt = _get_marketing(request)
    db = mkt["db"]
    if not db:
        return {"metrics": {}, "source": source, "period_days": days}

    metrics = await db.get_marketing_metrics(source=source, days=days)
    return {"metrics": metrics, "source": source, "period_days": days}


# ── Platforms ─────────────────────────────────────────────────────


@router.get("/platforms")
async def list_platforms(request: Request):
    """List connected marketing platforms (Ayrshare, Mailchimp, etc.)."""
    mkt = _get_marketing(request)
    db = mkt["db"]
    if not db:
        return {"platforms": []}

    platforms = await db.get_platform_connections()
    return {"platforms": platforms}
