"""Tenant isolation foundation.

Provides a ContextVar-based tenant context that flows through async calls.
Every data access should respect the current tenant's org_id.

Single-tenant mode uses org_id="default" — no functional change.
Multi-tenant mode extracts org_id from JWT claims.

Usage:
    from core.tenant import set_tenant, get_tenant, require_tenant

    # At request boundary (middleware or WS handler):
    set_tenant(TenantContext(org_id="org-abc", org_name="Acme", tier="pro"))

    # In data access layer:
    tenant = get_tenant()  # Returns TenantContext (never None)
    query = query.where(table.c.org_id == tenant.org_id)
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass

logger = logging.getLogger("nexus.tenant")

# Tier definitions (match licensing tiers)
TIER_FREE = "free"
TIER_PRO = "pro"
TIER_ENTERPRISE = "enterprise"

DEFAULT_ORG_ID = "default"
DEFAULT_ORG_NAME = "Default Organization"


@dataclass
class TenantContext:
    """Current tenant/organization context."""
    org_id: str = DEFAULT_ORG_ID
    org_name: str = DEFAULT_ORG_NAME
    tier: str = TIER_FREE

    @property
    def is_default(self) -> bool:
        """True if this is the default single-tenant org."""
        return self.org_id == DEFAULT_ORG_ID


# Default context — single-tenant mode
_DEFAULT_TENANT = TenantContext()

# ContextVar for async propagation
_current_tenant: ContextVar[TenantContext] = ContextVar(
    "current_tenant", default=_DEFAULT_TENANT
)


def set_tenant(ctx: TenantContext) -> None:
    """Set the current tenant context (call at request boundary)."""
    _current_tenant.set(ctx)


def get_tenant() -> TenantContext:
    """Get the current tenant context. Never returns None."""
    return _current_tenant.get()


def clear_tenant() -> None:
    """Reset to default tenant (end of request)."""
    _current_tenant.set(_DEFAULT_TENANT)


def require_tenant() -> TenantContext:
    """Get tenant context, raising if not set explicitly.

    Use this in code paths that MUST have a real tenant (multi-tenant mode).
    In single-tenant mode, the default org is always valid.
    """
    ctx = _current_tenant.get()
    if ctx.org_id == DEFAULT_ORG_ID:
        # In single-tenant mode, default is fine
        return ctx
    return ctx


def tenant_from_jwt(claims: dict) -> TenantContext:
    """Extract tenant context from JWT custom claims.

    Expected claims:
        nexus:org_id — organization ID
        nexus:org_name — organization display name (optional)
        nexus:license_tier — free/pro/enterprise (optional)
    """
    org_id = claims.get("nexus:org_id", "") or claims.get("org_id", "")
    if not org_id:
        return TenantContext()  # Default single-tenant

    return TenantContext(
        org_id=org_id,
        org_name=claims.get("nexus:org_name", "") or claims.get("name", org_id),
        tier=claims.get("nexus:license_tier", TIER_FREE),
    )
