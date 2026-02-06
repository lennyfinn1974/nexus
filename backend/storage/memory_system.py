"""Personal Memory System for Nexus Agent (PostgreSQL).

Tracks user preferences, interaction patterns, project context, and provides
intelligent context awareness across sessions.

Uses SQLAlchemy async sessions. Native JSONB columns replace json.loads/dumps.
Dataclasses are preserved for in-memory cache representation.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from dataclasses import dataclass, asdict

from storage.models import (
    UserPreferenceModel,
    ProjectContextModel,
    InteractionPatternModel,
    SessionContextModel,
    KnowledgeAssociation,
    UserGoal,
)

logger = logging.getLogger("nexus.memory")


@dataclass
class UserPreference:
    key: str
    value: str
    category: str
    confidence: float = 1.0
    last_updated: str = None
    frequency: int = 1


@dataclass
class ProjectContext:
    project_id: str
    name: str
    description: str
    status: str = "active"  # active, paused, completed, archived
    priority: int = 3  # 1-5 scale
    tags: List[str] = None
    files_involved: List[str] = None
    last_worked: str = None
    total_sessions: int = 0


@dataclass
class InteractionPattern:
    pattern_id: str
    description: str
    triggers: List[str]
    success_rate: float
    frequency: int
    last_seen: str
    context_type: str  # tool_usage, workflow, preference, timing


class PersonalMemorySystem:
    """Personal memory using PostgreSQL via SQLAlchemy sessions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._preferences_cache: Dict[str, UserPreference] = {}
        self._patterns_cache: Dict[str, dict] = {}
        self._active_projects: Dict[str, ProjectContext] = {}

    async def initialize(self):
        """Load caches from database. Tables are created by Alembic."""
        await self._load_caches()
        logger.info("Personal Memory System initialized")

    # Keep connect() as alias for backward compatibility
    async def connect(self):
        await self.initialize()

    async def close(self):
        """No-op. Engine lifecycle is external."""
        pass

    async def _load_caches(self):
        """Load frequently accessed data into memory."""
        async with self._session_factory() as session:
            # Load preferences
            result = await session.execute(select(UserPreferenceModel))
            prefs = result.scalars().all()
            for pref in prefs:
                self._preferences_cache[pref.key] = UserPreference(
                    key=pref.key,
                    value=pref.value,
                    category=pref.category,
                    confidence=pref.confidence,
                    last_updated=pref.last_updated.isoformat() if pref.last_updated else None,
                    frequency=pref.frequency,
                )

            # Load active projects (JSONB columns are already native Python types)
            result = await session.execute(
                select(ProjectContextModel)
                .where(ProjectContextModel.status == "active")
                .order_by(ProjectContextModel.last_worked.desc())
            )
            projects = result.scalars().all()
            for proj in projects:
                self._active_projects[proj.project_id] = ProjectContext(
                    project_id=proj.project_id,
                    name=proj.name,
                    description=proj.description,
                    status=proj.status,
                    priority=proj.priority,
                    tags=proj.tags or [],
                    files_involved=proj.files_involved or [],
                    last_worked=proj.last_worked.isoformat() if proj.last_worked else None,
                    total_sessions=proj.total_sessions,
                )

            # Load high-frequency patterns
            result = await session.execute(
                select(InteractionPatternModel)
                .where(InteractionPatternModel.frequency > 2)
                .order_by(InteractionPatternModel.frequency.desc())
                .limit(50)
            )
            patterns = result.scalars().all()
            for pattern in patterns:
                self._patterns_cache[pattern.pattern_id] = {
                    "pattern_id": pattern.pattern_id,
                    "description": pattern.description,
                    "triggers": pattern.triggers or [],
                    "success_rate": pattern.success_rate,
                    "frequency": pattern.frequency,
                    "context_type": pattern.context_type,
                    "first_seen": pattern.first_seen.isoformat() if pattern.first_seen else None,
                    "last_seen": pattern.last_seen.isoformat() if pattern.last_seen else None,
                }

    # ── User Preferences ────────────────────────────────────────

    async def learn_preference(self, key: str, value: str, category: str, confidence: float = 1.0):
        """Learn or reinforce a user preference."""
        now = datetime.now(timezone.utc)

        if key in self._preferences_cache:
            # Reinforce existing preference
            pref = self._preferences_cache[key]
            pref.frequency += 1
            pref.confidence = min(1.0, pref.confidence * 0.9 + confidence * 0.1)
            pref.last_updated = now.isoformat()
            if pref.value != value:
                pref.value = value
                pref.confidence = confidence
        else:
            pref = UserPreference(key, value, category, confidence, now.isoformat(), 1)
            self._preferences_cache[key] = pref

        async with self._session_factory() as session:
            stmt = pg_insert(UserPreferenceModel).values(
                key=key,
                value=value,
                category=category,
                confidence=confidence,
                frequency=pref.frequency,
                first_learned=now,
                last_updated=now,
            ).on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "value": value,
                    "confidence": confidence,
                    "frequency": pref.frequency,
                    "last_updated": now,
                },
            )
            await session.execute(stmt)
            await session.commit()

    async def get_preference(self, key: str, default: str = None) -> Optional[str]:
        """Get a user preference by key."""
        if key in self._preferences_cache:
            return self._preferences_cache[key].value
        return default

    async def get_preferences_by_category(self, category: str) -> Dict[str, str]:
        """Get all preferences in a category."""
        return {
            k: v.value for k, v in self._preferences_cache.items()
            if v.category == category
        }

    # ── Project Context ─────────────────────────────────────────

    async def create_project(self, name: str, description: str = "", tags: List[str] = None,
                           priority: int = 3) -> str:
        """Create a new project context."""
        project_id = f"proj_{hash(name + description) % 100000:05d}"
        now = datetime.now(timezone.utc)

        project = ProjectContext(
            project_id=project_id,
            name=name,
            description=description,
            priority=priority,
            tags=tags or [],
            files_involved=[],
            last_worked=now.isoformat(),
            total_sessions=0,
        )

        async with self._session_factory() as session:
            session.add(ProjectContextModel(
                project_id=project_id,
                name=name,
                description=description,
                priority=priority,
                tags=tags or [],
                files_involved=[],
                created_at=now,
                last_worked=now,
                total_sessions=0,
            ))
            await session.commit()

        self._active_projects[project_id] = project
        logger.info(f"Created project: {name} ({project_id})")
        return project_id

    async def get_active_projects(self) -> List[dict]:
        """Get all active projects."""
        return [asdict(p) for p in self._active_projects.values()]

    async def update_project(self, project_id: str, **kwargs):
        """Update project fields."""
        now = datetime.now(timezone.utc)
        values = {k: v for k, v in kwargs.items() if v is not None}
        values["last_worked"] = now

        async with self._session_factory() as session:
            await session.execute(
                update(ProjectContextModel)
                .where(ProjectContextModel.project_id == project_id)
                .values(**values)
            )
            await session.commit()

        if project_id in self._active_projects:
            proj = self._active_projects[project_id]
            for k, v in kwargs.items():
                if hasattr(proj, k):
                    setattr(proj, k, v)
            proj.last_worked = now.isoformat()

    # ── Interaction Patterns ────────────────────────────────────

    async def record_pattern(self, pattern_id: str, description: str, triggers: List[str],
                           context_type: str, success: bool = True):
        """Record or reinforce an interaction pattern."""
        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            existing = await session.get(InteractionPatternModel, pattern_id)
            if existing:
                existing.frequency += 1
                if success:
                    existing.success_rate = (
                        existing.success_rate * (existing.frequency - 1) + 1.0
                    ) / existing.frequency
                else:
                    existing.success_rate = (
                        existing.success_rate * (existing.frequency - 1)
                    ) / existing.frequency
                existing.last_seen = now
                await session.commit()

                self._patterns_cache[pattern_id] = {
                    "pattern_id": pattern_id,
                    "description": description,
                    "triggers": existing.triggers or [],
                    "success_rate": existing.success_rate,
                    "frequency": existing.frequency,
                    "context_type": context_type,
                    "first_seen": existing.first_seen.isoformat() if existing.first_seen else None,
                    "last_seen": now.isoformat(),
                }
            else:
                session.add(InteractionPatternModel(
                    pattern_id=pattern_id,
                    description=description,
                    triggers=triggers,
                    success_rate=1.0 if success else 0.0,
                    frequency=1,
                    context_type=context_type,
                    first_seen=now,
                    last_seen=now,
                ))
                await session.commit()

    # ── Session Tracking ────────────────────────────────────────

    async def start_session(self, session_id: str, conversation_id: str = None) -> int:
        """Record the start of a new session. Returns the DB row id."""
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            row = SessionContextModel(
                session_id=session_id,
                conversation_id=conversation_id,
                start_time=now,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.id

    async def end_session(self, row_id: int, **kwargs):
        """Record end-of-session data."""
        now = datetime.now(timezone.utc)
        values = {k: v for k, v in kwargs.items() if v is not None}
        values["end_time"] = now

        async with self._session_factory() as session:
            await session.execute(
                update(SessionContextModel)
                .where(SessionContextModel.id == row_id)
                .values(**values)
            )
            await session.commit()

    # ── Knowledge Associations ──────────────────────────────────

    async def associate_concepts(self, from_concept: str, to_concept: str,
                                relationship_type: str, source: str):
        """Create or reinforce a knowledge association."""
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            # Check for existing
            result = await session.execute(
                select(KnowledgeAssociation).where(
                    KnowledgeAssociation.from_concept == from_concept,
                    KnowledgeAssociation.to_concept == to_concept,
                    KnowledgeAssociation.relationship_type == relationship_type,
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.reinforced_count += 1
                existing.strength = min(1.0, existing.strength + 0.1)
            else:
                session.add(KnowledgeAssociation(
                    from_concept=from_concept,
                    to_concept=to_concept,
                    relationship_type=relationship_type,
                    strength=0.5,
                    created_from=source,
                    created_at=now,
                ))
            await session.commit()

    # ── User Goals ──────────────────────────────────────────────

    async def create_goal(self, goal_id: str, title: str, description: str = "",
                         goal_type: str = "general", target_date: datetime = None,
                         milestones: List[dict] = None, success_criteria: List[str] = None,
                         related_projects: List[str] = None) -> str:
        """Create a new user goal."""
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            session.add(UserGoal(
                goal_id=goal_id,
                title=title,
                description=description,
                goal_type=goal_type,
                target_date=target_date,
                milestones=milestones or [],
                success_criteria=success_criteria or [],
                related_projects=related_projects or [],
                created_at=now,
                last_updated=now,
            ))
            await session.commit()
        return goal_id

    async def update_goal_progress(self, goal_id: str, progress: float, status: str = None):
        """Update goal progress percentage and optionally status."""
        now = datetime.now(timezone.utc)
        values: dict = {"progress_percentage": progress, "last_updated": now}
        if status:
            values["status"] = status
        async with self._session_factory() as session:
            await session.execute(
                update(UserGoal).where(UserGoal.goal_id == goal_id).values(**values)
            )
            await session.commit()

    async def get_active_goals(self) -> List[dict]:
        """Get all active goals."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(UserGoal)
                .where(UserGoal.status == "active")
                .order_by(UserGoal.target_date.asc().nullslast())
            )
            goals = result.scalars().all()
            return [
                {
                    "goal_id": g.goal_id,
                    "title": g.title,
                    "description": g.description,
                    "goal_type": g.goal_type,
                    "status": g.status,
                    "target_date": g.target_date.isoformat() if g.target_date else None,
                    "progress_percentage": g.progress_percentage,
                    "milestones": g.milestones or [],
                    "success_criteria": g.success_criteria or [],
                    "related_projects": g.related_projects or [],
                    "created_at": g.created_at.isoformat() if g.created_at else None,
                    "last_updated": g.last_updated.isoformat() if g.last_updated else None,
                }
                for g in goals
            ]

    # ── Context Building ────────────────────────────────────────

    async def build_memory_context(self) -> str:
        """Build a context string from memory for the system prompt."""
        parts = []

        # Active projects
        if self._active_projects:
            projects = sorted(
                self._active_projects.values(),
                key=lambda p: p.last_worked or "",
                reverse=True,
            )[:5]
            parts.append("Active Projects:")
            for p in projects:
                parts.append(f"  - {p.name} (priority {p.priority})")

        # Key preferences
        if self._preferences_cache:
            high_conf = [
                p for p in self._preferences_cache.values()
                if p.confidence >= 0.7
            ]
            if high_conf:
                parts.append("User Preferences:")
                for p in sorted(high_conf, key=lambda x: x.frequency, reverse=True)[:10]:
                    parts.append(f"  - {p.key}: {p.value}")

        return "\n".join(parts) if parts else ""
