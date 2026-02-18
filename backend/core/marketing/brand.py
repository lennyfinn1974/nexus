"""Brand voice profiles — tone enforcement and vocabulary rules.

A brand profile defines how the Nexus agent (and sub-agents) should write
content for a specific business. Profiles are stored in PostgreSQL and
injected into the system prompt when generating marketing content.

Each profile includes:
- Tone (e.g. "warm and friendly", "professional and authoritative")
- Vocabulary rules (preferred words, banned words, jargon to avoid)
- Platform-specific guidelines (Instagram vs LinkedIn vs email voice)
- Example content snippets that demonstrate the brand voice
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("nexus.marketing.brand")


@dataclass
class BrandProfile:
    """A brand voice profile for content generation."""

    id: Optional[int] = None
    name: str = ""
    tone: str = ""                          # e.g. "warm, approachable, knowledgeable"
    vocabulary_rules: dict = field(default_factory=dict)  # {"preferred": [...], "banned": [...], "replacements": {...}}
    examples: list = field(default_factory=list)          # [{"platform": "instagram", "text": "..."}]
    platform_guidelines: dict = field(default_factory=dict)  # {"instagram": "...", "linkedin": "...", "email": "..."}
    is_default: bool = False
    org_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "tone": self.tone,
            "vocabulary_rules": self.vocabulary_rules,
            "examples": self.examples,
            "platform_guidelines": self.platform_guidelines,
            "is_default": self.is_default,
            "org_id": self.org_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BrandProfile:
        return cls(
            id=data.get("id"),
            name=data.get("name", ""),
            tone=data.get("tone", ""),
            vocabulary_rules=data.get("vocabulary_rules") or {},
            examples=data.get("examples") or [],
            platform_guidelines=data.get("platform_guidelines") or {},
            is_default=data.get("is_default", False),
            org_id=data.get("org_id"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def get_prompt_injection(self, platform: str = "") -> str:
        """Build a system prompt fragment enforcing this brand voice.

        This is injected into the LLM system prompt when generating
        marketing content so the agent writes in the brand's voice.
        """
        parts = [f"## Brand Voice: {self.name}"]

        if self.tone:
            parts.append(f"**Tone:** {self.tone}")

        # Vocabulary rules
        vocab = self.vocabulary_rules
        if vocab.get("preferred"):
            parts.append(f"**Preferred words/phrases:** {', '.join(vocab['preferred'])}")
        if vocab.get("banned"):
            parts.append(f"**Never use:** {', '.join(vocab['banned'])}")
        if vocab.get("replacements"):
            replacements = [f"\"{k}\" → \"{v}\"" for k, v in vocab["replacements"].items()]
            parts.append(f"**Word replacements:** {'; '.join(replacements)}")

        # Platform-specific guidelines
        if platform and platform in self.platform_guidelines:
            parts.append(f"\n**{platform.title()} Guidelines:**")
            parts.append(self.platform_guidelines[platform])
        elif self.platform_guidelines:
            for plat, guide in self.platform_guidelines.items():
                parts.append(f"\n**{plat.title()} Guidelines:**")
                parts.append(guide)

        # Examples
        if self.examples:
            parts.append("\n**Example content (match this voice):**")
            for ex in self.examples[:3]:  # Max 3 examples to save tokens
                plat = ex.get("platform", "general")
                text = ex.get("text", "")
                parts.append(f"- [{plat}] {text[:200]}")

        return "\n".join(parts)


class BrandVoiceManager:
    """Manages brand voice profiles in PostgreSQL.

    Profiles are cached in memory after first load. Changes go through
    the DB and update the cache.
    """

    def __init__(self, db: Any):
        self.db = db
        self._cache: dict[int, BrandProfile] = {}
        self._default_id: Optional[int] = None

    async def load_all(self) -> list[BrandProfile]:
        """Load all brand profiles from the database."""
        rows = await self.db.get_brand_profiles()
        profiles = []
        for row in rows:
            profile = BrandProfile.from_dict(row)
            self._cache[profile.id] = profile
            if profile.is_default:
                self._default_id = profile.id
            profiles.append(profile)
        logger.info(f"Loaded {len(profiles)} brand profile(s)")
        return profiles

    @property
    def default_profile(self) -> Optional[BrandProfile]:
        """Get the default brand profile (if set)."""
        if self._default_id and self._default_id in self._cache:
            return self._cache[self._default_id]
        # Fall back to first profile
        if self._cache:
            return next(iter(self._cache.values()))
        return None

    def get(self, profile_id: int) -> Optional[BrandProfile]:
        """Get a brand profile by ID from cache."""
        return self._cache.get(profile_id)

    async def create(self, data: dict) -> BrandProfile:
        """Create a new brand profile."""
        row = await self.db.create_brand_profile(data)
        profile = BrandProfile.from_dict(row)
        self._cache[profile.id] = profile
        if profile.is_default:
            # Unset any other default
            for p in self._cache.values():
                if p.id != profile.id:
                    p.is_default = False
            self._default_id = profile.id
        logger.info(f"Brand profile created: {profile.name} (id={profile.id})")
        return profile

    async def update(self, profile_id: int, data: dict) -> Optional[BrandProfile]:
        """Update an existing brand profile."""
        row = await self.db.update_brand_profile(profile_id, data)
        if not row:
            return None
        profile = BrandProfile.from_dict(row)
        self._cache[profile.id] = profile
        if profile.is_default:
            for p in self._cache.values():
                if p.id != profile.id:
                    p.is_default = False
            self._default_id = profile.id
        logger.info(f"Brand profile updated: {profile.name} (id={profile.id})")
        return profile

    async def delete(self, profile_id: int) -> bool:
        """Delete a brand profile."""
        deleted = await self.db.delete_brand_profile(profile_id)
        if deleted:
            self._cache.pop(profile_id, None)
            if self._default_id == profile_id:
                self._default_id = None
            logger.info(f"Brand profile deleted: id={profile_id}")
        return deleted

    def get_prompt_for_content(
        self,
        profile_id: Optional[int] = None,
        platform: str = "",
    ) -> str:
        """Get the brand voice prompt injection for content generation.

        If no profile_id is specified, uses the default profile.
        Returns empty string if no profiles exist.
        """
        profile = None
        if profile_id:
            profile = self.get(profile_id)
        if not profile:
            profile = self.default_profile
        if not profile:
            return ""
        return profile.get_prompt_injection(platform=platform)
