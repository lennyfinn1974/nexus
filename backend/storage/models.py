"""SQLAlchemy ORM models for Nexus.

All 20 tables: 12 core (conversations, messages, skills, tasks, settings,
settings_audit, user_preferences, project_contexts, interaction_patterns,
session_contexts, knowledge_associations, user_goals) plus 6 auth/security
tables (users, whitelist, sessions, blocked_ips, auth_audit, rate_limits)
plus 2 Telegram pairing tables (telegram_pairings, pairing_codes).
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ── Core Tables ──────────────────────────────────────────────────


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False, default="New Conversation")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    model_used = Column(String, nullable=True)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'system')", name="ck_messages_role"),
        Index("idx_messages_conversation", "conversation_id", "created_at"),
    )


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    summary_text = Column(Text, nullable=False)
    messages_covered = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("idx_conv_summaries_conv", "conversation_id"),
    )


class Skill(Base):
    __tablename__ = "skills"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    domain = Column(String, nullable=True)
    file_path = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
    usage_count = Column(Integer, default=0)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_skills_domain", "domain"),)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    payload = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_tasks_status",
        ),
        Index("idx_tasks_status", "status", "created_at"),
    )


# ── Settings Tables ──────────────────────────────────────────────


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False, default="")
    encrypted = Column(Boolean, nullable=False, default=False)
    category = Column(String, nullable=False, default="general")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_by = Column(String, nullable=False, default="system")


class SettingsAudit(Base):
    __tablename__ = "settings_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    changed_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    changed_by = Column(String, nullable=False, default="admin")


# ── Memory System Tables ─────────────────────────────────────────


class UserPreferenceModel(Base):
    __tablename__ = "user_preferences"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)
    category = Column(String, nullable=False)
    confidence = Column(Float, default=1.0)
    frequency = Column(Integer, default=1)
    first_learned = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_updated = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (Index("idx_preferences_category", "category"),)


class ProjectContextModel(Base):
    __tablename__ = "project_contexts"

    project_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, default="active")
    priority = Column(Integer, default=3)
    tags = Column(JSONB, nullable=True)
    files_involved = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_worked = Column(DateTime(timezone=True), nullable=True)
    total_sessions = Column(Integer, default=0)
    metadata_ = Column("metadata", JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'paused', 'completed', 'archived')", name="ck_projects_status"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="ck_projects_priority"),
        Index("idx_projects_status", "status", "last_worked"),
    )


class InteractionPatternModel(Base):
    __tablename__ = "interaction_patterns"

    pattern_id = Column(String, primary_key=True)
    description = Column(Text, nullable=False)
    triggers = Column(JSONB, nullable=False)
    success_rate = Column(Float, default=1.0)
    frequency = Column(Integer, default=1)
    context_type = Column(String, nullable=False)
    first_seen = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_seen = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    metadata_ = Column("metadata", JSONB, nullable=True)

    __table_args__ = (Index("idx_patterns_type", "context_type", "frequency"),)


class SessionContextModel(Base):
    __tablename__ = "session_contexts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False)
    conversation_id = Column(String, nullable=True)
    start_time = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    end_time = Column(DateTime(timezone=True), nullable=True)
    projects_worked = Column(JSONB, nullable=True)
    tools_used = Column(JSONB, nullable=True)
    skills_used = Column(JSONB, nullable=True)
    topics_discussed = Column(JSONB, nullable=True)
    productivity_score = Column(Float, nullable=True)
    user_satisfaction = Column(Float, nullable=True)
    key_achievements = Column(JSONB, nullable=True)
    challenges_faced = Column(JSONB, nullable=True)
    continuation_context = Column(Text, nullable=True)

    __table_args__ = (Index("idx_sessions_time", "start_time", "conversation_id"),)


class KnowledgeAssociation(Base):
    __tablename__ = "knowledge_associations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    from_concept = Column(String, nullable=False)
    to_concept = Column(String, nullable=False)
    relationship_type = Column(String, nullable=False)
    strength = Column(Float, default=1.0)
    created_from = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    reinforced_count = Column(Integer, default=1)

    __table_args__ = (Index("idx_knowledge_concepts", "from_concept", "to_concept"),)


class UserGoal(Base):
    __tablename__ = "user_goals"

    goal_id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    goal_type = Column(String, default="general")
    status = Column(String, default="active")
    target_date = Column(DateTime(timezone=True), nullable=True)
    progress_percentage = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_updated = Column(DateTime(timezone=True), nullable=True)
    milestones = Column(JSONB, nullable=True)
    success_criteria = Column(JSONB, nullable=True)
    related_projects = Column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'paused', 'achieved', 'abandoned')", name="ck_goals_status"),
        Index("idx_goals_status", "status", "target_date"),
    )


# ── Auth / Security Tables ───────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=True)
    picture = Column(String, nullable=True)
    role = Column(String, nullable=False, default="user")
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_login = Column(DateTime(timezone=True), nullable=True)
    last_ip = Column(String, nullable=True)

    sessions = relationship("ActiveSession", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
        Index("idx_users_email", "email"),
    )


class Whitelist(Base):
    __tablename__ = "whitelist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, nullable=False, unique=True)
    added_by = Column(String, nullable=True)
    added_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ActiveSession(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    refresh_token_hash = Column(String, nullable=False)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="sessions")

    __table_args__ = (
        Index("idx_sessions_user", "user_id"),
        Index("idx_sessions_expires", "expires_at"),
    )


class BlockedIP(Base):
    __tablename__ = "blocked_ips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip_address = Column(String, nullable=False, unique=True)
    reason = Column(Text, nullable=True)
    blocked_by = Column(String, nullable=True)
    blocked_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (Index("idx_blocked_ips_addr", "ip_address"),)


class AuthAudit(Base):
    __tablename__ = "auth_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String, nullable=False)
    user_id = Column(String, nullable=True)
    email = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("idx_auth_audit_type", "event_type", "created_at"),
        Index("idx_auth_audit_ip", "ip_address", "created_at"),
    )


# ── Telegram Pairing Tables ────────────────────────────────────


class TelegramPairing(Base):
    __tablename__ = "telegram_pairings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id = Column(String, nullable=False, unique=True)
    telegram_username = Column(String, nullable=True)
    telegram_first_name = Column(String, nullable=True)
    conversation_id = Column(String, nullable=True)
    paired_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_active = Column(DateTime(timezone=True), nullable=True)
    active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("idx_tg_pairings_user", "telegram_user_id"),
    )


class PairingCode(Base):
    __tablename__ = "pairing_codes"

    code = Column(String(8), primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, nullable=False, default=False)
    used_by_telegram_id = Column(String, nullable=True)