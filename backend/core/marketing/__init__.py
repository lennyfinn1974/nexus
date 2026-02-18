"""Nexus Marketing Agency — core marketing framework.

Modules:
    brand       — Brand voice profiles and tone enforcement
    content     — Content workflow state machine (draft → review → published)
    campaign    — Campaign planner, budget tracking, calendar
    attribution — Multi-touch attribution models, UTM builder
"""

from core.marketing.brand import BrandProfile, BrandVoiceManager
from core.marketing.content import ContentItem, ContentStatus, ContentWorkflow
from core.marketing.campaign import Campaign, CampaignManager, CampaignStatus

__all__ = [
    "BrandProfile",
    "BrandVoiceManager",
    "ContentItem",
    "ContentStatus",
    "ContentWorkflow",
    "Campaign",
    "CampaignManager",
    "CampaignStatus",
]
