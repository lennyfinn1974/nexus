# Nexus Licensing & Marketplace Architecture

## Enterprise SaaS Licensing, Authentication, Plugin Marketplace & Billing

**Status:** Architecture Draft (Feb 14, 2026)
**Target:** Phase 7 — After Redis Clustering (Phase 6) is complete
**Narrative:** "Nexus-Inside" — Free to download, pay for enterprise power

---

## 1. Vision

Transform Nexus from an open-source project into a commercially viable enterprise platform with:

- **Free tier** that's genuinely useful (single agent, core plugins, local models)
- **Pro tier** ($49/mo) for teams who need clustering, all plugins, Claude API access
- **Enterprise tier** (custom pricing) for SSO/SAML, on-prem, dedicated support
- **Plugin marketplace** where third-party developers build and sell plugins

### The Open-Core Model

Inspired by GitLab, n8n, and Grafana — the source code is visible and self-hostable, but enterprise features are gated behind a license. This is the most sustainable model for developer tools in 2026.

```
┌────────────────────────────────────────────────────────────┐
│                    FREE TIER (Open-Source)                  │
│  Single agent, Ollama (local), 5 core plugins, 100 convos  │
│  Community support, basic memory, no clustering             │
├────────────────────────────────────────────────────────────┤
│                    PRO TIER ($49/month)                     │
│  5 agents (clustered), Ollama + Claude, all built-in        │
│  plugins, sub-agents, vector memory, audit logging,         │
│  marketplace access, API access, priority support           │
├────────────────────────────────────────────────────────────┤
│              ENTERPRISE TIER (Custom Pricing)               │
│  Unlimited agents, all models, custom plugins,              │
│  SSO/SAML, on-prem deployment, dedicated support,           │
│  compliance (SOC2), SLA, graph memory                       │
├────────────────────────────────────────────────────────────┤
│              PLUGIN MARKETPLACE (Revenue Share)             │
│  Third-party developers sell premium plugins                │
│  85/15 split (developer keeps 85%)                          │
│  0% commission in Year 1 to build ecosystem                 │
└────────────────────────────────────────────────────────────┘
```

---

## 2. Tier Structure (Detailed)

| Feature | Free | Pro ($49/mo) | Enterprise (Custom) |
|---|---|---|---|
| **Agents** | 1 | 5 (clustered) | Unlimited |
| **Models** | Ollama (local only) | Ollama + Claude API | All (including Claude Code) |
| **Plugins** | 5 core built-in | All built-in + marketplace | Custom + marketplace + bespoke |
| **Sub-agents** | No | Yes (3 concurrent) | Yes (unlimited) |
| **Memory** | Basic (PostgreSQL) | Advanced (+ vector search) | Full (+ graph, cross-cluster) |
| **Conversations** | 100/month | Unlimited | Unlimited |
| **Credits** | 1,000/month | 50,000/month | Custom allocation |
| **Auth** | Local (API key) | Email/password + org mgmt | + SSO/SAML, SCIM |
| **Audit** | No | Basic logging | Full audit trail, compliance |
| **Support** | Community (GitHub) | Priority (48h SLA) | Dedicated (4h SLA, named engineer) |
| **Deployment** | Self-hosted only | Cloud + self-hosted | On-prem + cloud + dedicated |
| **API access** | No | Yes | Yes + webhooks |
| **Clustering** | No | Yes (Phase 6) | Yes + multi-region |
| **Planner** | Basic | Full (multi-step) | Full + custom strategies |
| **Reminders** | 5 active | Unlimited | Unlimited + team reminders |
| **Web understanding** | Basic HTTP | + Headless render | + Custom extractors |

### Credit Economy

```
1 credit = $0.001 USD

Credit costs by operation:
  Ollama request (any size):          0 credits (free — local compute)
  Claude Sonnet 1K input tokens:      3 credits
  Claude Sonnet 1K output tokens:     15 credits
  Claude Opus 1K input tokens:        15 credits
  Claude Opus 1K output tokens:       75 credits
  Plugin tool call:                   1 credit
  Sub-agent orchestration (per agent): 5 credits + model tokens
  Web fetch (headless render):        2 credits
  Marketplace plugin tool call:       Per plugin pricing
```

**Key principle:** Local model usage (Ollama) is always free. Credits only apply to cloud-hosted model usage and premium features. This aligns with Nexus's local-first philosophy.

---

## 3. Authentication Architecture

### 3.1 Tri-Mode Design

Nexus must support three authentication modes, detected automatically by configuration:

```
if KEYCLOAK_URL is configured:
    mode = "enterprise"    → Keycloak OIDC/SAML validation
elif AUTH_PROVIDER == "auth0":
    mode = "cloud_saas"    → Auth0 JWT validation
else:
    mode = "local"         → API key / open access (current behaviour)
```

**Local Mode** (default, zero dependencies):
- No external auth provider needed
- Single-user, API key in DB (existing `ADMIN_ACCESS_KEY` pattern)
- All open-source features available
- Target: developers, self-hosted hobbyists

**Cloud SaaS Mode** (Auth0 or Clerk):
- Multi-tenant with organization isolation
- Email/password + social login
- Organization management, team invitations
- License tier enforcement via JWT custom claims
- Stripe billing integration

**Enterprise Mode** (Keycloak, self-hosted):
- Customer runs own Keycloak (or connects existing IdP)
- SAML 2.0 + OIDC federation per organization
- SCIM provisioning from enterprise IdP (Azure AD, Okta)
- Offline-capable signed license files
- Air-gapped deployment support

### 3.2 Recommended Auth Provider: Keycloak (Primary) + Auth0 (Optional Cloud)

**Why Keycloak as primary:**

| Requirement | Keycloak | Auth0 | Clerk |
|---|---|---|---|
| Self-hosted (on-prem) | YES | NO | NO |
| SAML SSO | Best-in-class | Good | Limited |
| Multi-tenant (Realms) | YES (native) | YES (Orgs) | YES (Orgs) |
| Open-source | YES (Apache 2.0) | NO | NO |
| Cost at scale | Free (self-hosted) | $3K-$10K+/mo | $800+/mo |
| SCIM provisioning | YES | YES (Enterprise) | Enterprise only |
| RBAC | Comprehensive | Good | Good |
| Local mode fallback | YES | NO | NO |

**Auth0 as optional cloud alternative:** Detect `AUTH0_DOMAIN` config and support Auth0 JWTs alongside Keycloak. Both produce standard OIDC tokens — the backend validates either.

**Keycloak resource cost:** Java runtime requires 512MB-2GB RAM. Acceptable for enterprise infrastructure. For lightweight/edge deployments, Ory (Go-based, ~100MB RAM) is the alternative.

### 3.3 RBAC Model

```
Roles:
  owner:     Full control, billing, can delete org
  admin:     Manage members, configure agents, view audit logs
  operator:  Run agents, create conversations, manage skills
  viewer:    Read-only access to conversations and dashboards
  api_only:  Headless access for CI/CD pipelines

Permissions:
  read:conversations     write:conversations
  read:agents            write:agents
  manage:skills          manage:plugins
  manage:members         admin:settings
  admin:billing          read:audit
  api:execute
```

### 3.4 JWT Token Structure

```json
{
  "sub": "user_abc123",
  "iss": "https://auth.nexus.example.com",
  "aud": "https://api.nexus.example.com",
  "exp": 1739500000,
  "iat": 1739456789,

  "nexus:org_id": "org_xyz789",
  "nexus:org_name": "acme-corp",
  "nexus:license_tier": "enterprise",
  "nexus:features": ["sso", "clustering", "audit", "api_access", "sub_agents"],
  "nexus:max_agents": 10,
  "nexus:roles": ["admin"],
  "nexus:permissions": ["read:conversations", "write:agents", "admin:settings"]
}
```

### 3.5 API Key Management

For headless/CLI/agent access (M2M), manage API keys in PostgreSQL (not Auth0 M2M tokens — avoids quota costs):

```
Table: api_keys
  id:           UUID
  key_hash:     VARCHAR (SHA-256 of the key, never store plaintext)
  org_id:       UUID (FK to organizations)
  user_id:      UUID (FK to users, nullable for org-level keys)
  name:         VARCHAR ("CI Pipeline", "Telegram Bot", etc.)
  permissions:  JSONB (same permission strings as JWT)
  created_at:   TIMESTAMP
  last_used_at: TIMESTAMP
  expires_at:   TIMESTAMP (nullable for non-expiring)
  revoked:      BOOLEAN
```

Backend accepts either `Authorization: Bearer <JWT>` or `X-API-Key: <key>` header.

---

## 4. License System

### 4.1 Dual License Validation

**Cloud/SaaS customers:** License tier determined by Stripe subscription, injected into JWT custom claims at login. No license key needed.

**Self-hosted/on-prem customers:** Signed license file downloaded from Nexus portal after purchase. Validated locally with embedded public key.

### 4.2 License Key Format

```
NEXUS-PRO-K4M7X9A2B5D8F3G6H1J4L7N0P3R6S9T2V5W8Y1Z4

Structure: NEXUS-{PLAN}-{BASE32(RSA_SIGNED_PAYLOAD)}

Payload:
{
  "key_id": "lic_abc123",
  "org_id": "org_xyz789",
  "plan": "pro",
  "features": ["clustering", "all_plugins", "sub_agents", "vector_memory"],
  "max_agents": 5,
  "seats": 10,
  "issued_at": 1739456789,
  "expires_at": 1771000000,
  "maintenance_until": 1771000000,
  "instance_binding": null          // null = any instance, or specific instance_id
}

Signature: RSA-2048-PSS (private key on Nexus licensing server)
Validation: RSA public key embedded in Nexus binary
```

### 4.3 Validation Flow

```
Startup:
  1. Read NEXUS_LICENSE_KEY from env var or DB config
  2. Decode Base32 → extract payload + signature
  3. Verify RSA signature with embedded public key
  4. Check expiry, seat count, feature list
  5. Cache validation result in memory
  6. Re-check every 24h (online) or never (offline/on-prem)

Per-request:
  7. License middleware injects plan + features into request state
  8. Feature-gated endpoints check request.state.features
  9. Credit-consuming endpoints check request.state.credits_remaining
```

### 4.4 Grace Periods & Failure Modes

| Scenario | Behaviour |
|---|---|
| Payment fails | 7-day grace period → downgrade to Free (never lock out) |
| License expired (self-hosted) | 14-day grace period → features restricted to Free tier |
| License server unreachable | Continue with cached validation for 30 days |
| Credits exhausted | Ollama (local) still works, cloud models blocked |
| Org deactivated | 90-day data retention, can reactivate |

**Principle:** Never delete data, never hard-lock. Graceful degradation to Free tier.

---

## 5. Feature Gating (FastAPI Middleware)

### 5.1 License Middleware

```python
# backend/middleware/license.py

class LicenseMiddleware:
    """Validates license and injects plan/features into request state."""

    async def __call__(self, request: Request, call_next):
        org = request.state.organization  # set by auth middleware
        license = await license_cache.get(org.id)

        request.state.plan = license.plan
        request.state.features = license.features
        request.state.credits_remaining = license.credits_remaining

        response = await call_next(request)
        return response
```

### 5.2 Feature Gate Decorator

```python
@router.post("/api/cluster/start")
@require_feature("clustering")
async def start_cluster(request: Request):
    ...

@router.post("/api/sub-agents/orchestrate")
@require_feature("sub_agents")
async def orchestrate(request: Request):
    ...

@router.post("/api/chat")
@require_credits(1)  # base cost, actual tokens metered separately
async def chat(request: Request):
    ...
```

### 5.3 Plan-to-Feature Mapping (Configuration, not code)

```python
PLAN_FEATURES = {
    "free": {
        "max_agents": 1,
        "max_plugins": 5,
        "max_conversations": 100,
        "clustering": False,
        "sub_agents": False,
        "sso_saml": False,
        "audit_logging": False,
        "api_access": False,
        "vector_memory": False,
        "models": ["ollama"],
        "credits_monthly": 1000,
    },
    "pro": {
        "max_agents": 5,
        "max_plugins": -1,         # unlimited
        "max_conversations": -1,
        "clustering": True,
        "sub_agents": True,
        "sso_saml": False,
        "audit_logging": True,
        "api_access": True,
        "vector_memory": True,
        "models": ["ollama", "claude"],
        "credits_monthly": 50000,
    },
    "enterprise": {
        "max_agents": -1,
        "max_plugins": -1,
        "max_conversations": -1,
        "clustering": True,
        "sub_agents": True,
        "sso_saml": True,
        "audit_logging": True,
        "api_access": True,
        "vector_memory": True,
        "graph_memory": True,
        "custom_plugins": True,
        "on_prem": True,
        "models": ["ollama", "claude", "claude_code"],
        "credits_monthly": -1,    # custom
    }
}
```

### 5.4 Integration Points with Existing Codebase

| File | Gate | Feature |
|---|---|---|
| `core/agent_runner.py` | `max_agents` check before spawning | Clustering agent count |
| `core/sub_agent.py` | `require_feature("sub_agents")` | Sub-agent orchestration |
| `models/router.py` | Filter `models` by plan | Model access per tier |
| `plugins/manager.py` | `max_plugins` + `custom_plugins` | Plugin loading limits |
| `core/cluster/` | `require_feature("clustering")` | Entire clustering module |
| `routers/api.py` | `require_feature("api_access")` | REST API endpoints |
| `core/context_manager.py` | `max_conversations` per billing period | Conversation limits |
| `storage/memory_system.py` | `require_feature("vector_memory")` | Vector index features |

---

## 6. Billing Integration (Stripe)

### 6.1 Stripe Objects

```
Products:
  - Nexus Free         (no Stripe object, default)
  - Nexus Pro          (product_id: prod_nexus_pro)
  - Nexus Enterprise   (product_id: prod_nexus_enterprise)

Prices:
  - Pro Monthly:       $49/mo recurring
  - Pro Annual:        $490/yr recurring (2 months free)
  - Pro Usage:         $0.001/credit metered (overage)
  - Enterprise:        Custom (quoted per deal)

Subscription = Pro Monthly + Pro Usage (metered)
```

### 6.2 Usage Metering

```python
# Report usage to Stripe every hour (or per-request for high-value ops)
stripe.SubscriptionItem.create_usage_record(
    subscription_item_id,
    quantity=credits_consumed,
    timestamp=now,
    action="increment"  # CRITICAL: increment, not set
)

# Stripe bills: $49/month + (credits_used - 50,000 included) * $0.001
```

### 6.3 Webhook Provisioning Flow

```
Stripe Event                    → Nexus Action
─────────────────────────────────────────────────────────
checkout.session.completed      → Create org + assign plan + generate license key
customer.subscription.updated   → Update plan, add/remove features in real-time
invoice.paid                    → Reset monthly credits, update billing period
invoice.payment_failed          → Enter 7-day grace period, notify admin
customer.subscription.deleted   → Downgrade to Free, retain data 90 days
customer.subscription.trial_end → Send conversion email, in-app upgrade prompt
```

### 6.4 Self-Service via Stripe Customer Portal

Stripe's hosted Customer Portal handles:
- View/download invoices
- Update payment method
- Change plan (upgrade/downgrade)
- Cancel subscription
- Update billing email

This saves building a billing management UI. Link from Admin UI → Stripe Portal.

---

## 7. Plugin Marketplace

### 7.1 Plugin Types

| Type | Description | Examples | Monetisation |
|---|---|---|---|
| **Core** | Ships with Nexus, always free | macos, terminal, brave, sovereign | N/A |
| **Community** | Open-source, free | GitHub improvements, custom formatters | Free |
| **Premium** | Verified publishers, paid | Enterprise CRM, advanced analytics | Subscription/usage |
| **SaaS-connected** | Free plugin, paid external | DB monitoring, cloud deploy | External billing |

### 7.2 Plugin Manifest (extends existing system)

```yaml
# nexus-plugin.yaml
name: "enterprise-crm"
version: "2.1.0"
publisher: "acme-integrations"
publisher_id: "pub_a1b2c3d4"
description: "Salesforce + HubSpot CRM integration"
license: "commercial"

pricing:
  model: "subscription"     # one-time | subscription | usage | freemium
  monthly_price_usd: 29.00
  trial_days: 14

permissions:
  network:
    - "api.salesforce.com"
    - "api.hubspot.com"
  tools_provided:
    - name: "crm_search_contacts"
      tier: "free"
    - name: "crm_sync_pipeline"
      tier: "premium"
  file_access: []
  max_rate: 30

checksum: "sha256:a1b2c3..."
signature: "ed25519:publisher_pub_a1b2c3d4:..."
marketplace_attestation: "ed25519:nexus_marketplace:..."
```

### 7.3 Revenue Share Model

| Phase | Developer Keep | Nexus Take | Timing |
|---|---|---|---|
| **Launch (Year 1)** | 100% | 0% | Build ecosystem, attract developers |
| **Growth (Year 2)** | 90% | 10% | Modest sustainable take |
| **Mature (Year 3+)** | 85% | 15% | Industry-standard (Shopify/Stripe level) |

Additional:
- First $10K/year per developer: 0% commission always
- Open-source plugins with premium tiers: 5% (not 15%)
- Stripe processing fees (2.9% + $0.30) borne by Nexus, not developer

### 7.4 Security Review Pipeline

**Automated (every submission):**
1. Manifest schema validation
2. Dependency audit (Snyk/OSV for known CVEs)
3. Static analysis (Bandit + semgrep — no `eval()`, no shell injection, no hardcoded secrets)
4. Permission verification (declared vs actual network/file access)
5. Size + resource checks (<50MB, no unexpected binaries)

**Manual (initial submission + major updates):**
1. Code review (data handling, security practices, quality)
2. Functionality test in sandboxed Nexus instance
3. Timeline: 3-5 business days

**Post-approval monitoring:**
- Crash rate tracking
- Weekly review of user reports
- Periodic dependency re-scanning
- Auto-delist if crash rate >5% or unresolved security issues

### 7.5 Plugin Sandboxing Evolution

| Phase | Isolation Level | Mechanism |
|---|---|---|
| **Now** | In-process with `allowed_dirs` + `rate_limit` | Existing `NexusPlugin` base class |
| **Near-term** | Subprocess isolation | JSON-RPC over stdio (like MCP protocol) |
| **Medium-term** | Declared permissions enforced | Manifest permissions checked at runtime |
| **Long-term** | WASM sandbox via Extism | Maximum isolation for untrusted third-party |

### 7.6 Developer SDK & Onboarding

```bash
# 1. Install SDK
pip3 install nexus-plugin-sdk

# 2. Scaffold a new plugin
nexus plugin init my-crm-connector

# 3. Develop with hot-reload
nexus plugin dev

# 4. Run automated security checks
nexus plugin test

# 5. Package (signs with developer key)
nexus plugin package

# 6. Publish to marketplace
nexus plugin publish
```

**Developer Portal (web):**
- Publisher registration (identity verification via Stripe Identity)
- Plugin management dashboard (versions, downloads, revenue, ratings)
- API key management
- Analytics (install funnel, tool call heatmaps, error rates)
- Revenue dashboard + payout management (Stripe Connect)

### 7.7 Payment Infrastructure

**Primary:** Stripe Connect (Express accounts) — developers connect Stripe, Nexus routes payments, auto-splits revenue
**Tax handling:** Stripe handles 1099/W-8 for US developers, VAT for EU
**Payouts:** Configurable (daily, weekly, monthly) via Stripe Connect

---

## 8. Onboarding Flow

### 8.1 New User Journey

```
1. DOWNLOAD
   ↓ User downloads Nexus (Docker, pip, binary)
   ↓ Runs locally — instant value with Ollama
   ↓ Free tier, local mode, no auth required

2. EXPLORE
   ↓ Uses core plugins (terminal, web, macOS)
   ↓ Hits conversation limit (100/month)
   ↓ Sees "Upgrade to Pro" prompts in Chat UI

3. SIGN UP
   ↓ Creates account on Nexus Cloud (or self-hosted Keycloak)
   ↓ 14-day Pro trial (no credit card required)
   ↓ Full feature access during trial

4. CONVERT
   ↓ Trial expiring → upgrade prompt with Stripe Checkout
   ↓ Enters payment → Stripe webhook provisions license
   ↓ Downloads license key for self-hosted (or auto-provisioned for cloud)

5. TEAM
   ↓ Creates organization, invites team members
   ↓ Assigns roles (admin, operator, viewer)
   ↓ Enables clustering (adds Secondary agents)

6. ENTERPRISE
   ↓ Needs SSO/SAML, on-prem, compliance
   ↓ Contacts sales → custom contract
   ↓ Deploys Keycloak + Nexus on their infrastructure
   ↓ Signed license file for offline validation
```

### 8.2 Admin UI Integration

New pages in Admin UI:

| Page | Content |
|---|---|
| **Billing** | Current plan, usage dashboard, credit balance, upgrade/downgrade, Stripe Portal link |
| **License** | License key entry (self-hosted), validation status, features list, expiry |
| **Organization** | Team members, roles, invitations, API keys |
| **Marketplace** | Browse/install plugins, manage installed, plugin settings |
| **Usage** | Credit consumption chart, cost breakdown by model/feature, projected costs |

---

## 9. New Files & Modules

```
backend/
├── middleware/
│   ├── auth.py                  # NEW — JWT/API key validation, tri-mode detection
│   ├── license.py               # NEW — License validation, feature injection
│   └── credits.py               # NEW — Credit checking and deduction
│
├── licensing/
│   ├── __init__.py              # License manager (online + offline validation)
│   ├── keys.py                  # License key generation/validation (RSA)
│   ├── plans.py                 # Plan-to-feature mapping configuration
│   ├── credits.py               # Credit ledger (PostgreSQL-backed)
│   └── offline.py               # Offline license file validator
│
├── billing/
│   ├── __init__.py              # Stripe client initialization
│   ├── subscriptions.py         # Subscription management
│   ├── usage.py                 # Usage metering and reporting to Stripe
│   └── webhooks.py              # Stripe webhook handler (idempotent)
│
├── marketplace/
│   ├── __init__.py              # Marketplace manager
│   ├── registry.py              # Plugin registry (versions, publishers, ratings)
│   ├── installer.py             # Download, verify, install plugins
│   ├── reviewer.py              # Automated security review pipeline
│   └── billing.py               # Marketplace billing (Stripe Connect)
│
├── auth/
│   ├── __init__.py              # Auth provider abstraction
│   ├── keycloak.py              # Keycloak OIDC client
│   ├── auth0.py                 # Auth0 OIDC client (optional)
│   ├── local.py                 # Local API key auth (existing pattern)
│   ├── organizations.py         # Organization CRUD
│   ├── api_keys.py              # API key management
│   └── rbac.py                  # Role/permission checking
│
└── routers/
    ├── billing.py               # NEW — /api/billing/* endpoints
    ├── marketplace.py           # NEW — /api/marketplace/* endpoints
    └── organizations.py         # NEW — /api/orgs/* endpoints
```

### Dependencies to Add

```
# Authentication
python-jose[cryptography]>=3.3.0    # JWT validation
cryptography>=42.0.0                 # RSA license key signing

# Billing
stripe>=8.0.0                        # Stripe SDK

# Marketplace security
bandit>=1.7.0                        # Python security linter (plugin review)
```

---

## 10. Implementation Phases

### Phase 7A: Auth Foundation (3-4 days)

| Step | Task |
|---|---|
| 1 | Create `auth/` module with tri-mode detection (local/cloud/enterprise) |
| 2 | Create `middleware/auth.py` — JWT validation (Keycloak/Auth0) + API key fallback |
| 3 | Create `auth/organizations.py` — org CRUD in PostgreSQL |
| 4 | Create `auth/api_keys.py` — API key generation, hashing, validation |
| 5 | Create `auth/rbac.py` — role/permission checking |
| 6 | DB migrations: `organizations`, `org_members`, `api_keys` tables |
| 7 | Wire auth middleware into `app.py` (backwards compatible — local mode default) |

**Verification:** Existing single-user mode works unchanged. Keycloak JWT accepted when configured.

### Phase 7B: License System (2-3 days)

| Step | Task |
|---|---|
| 1 | Create `licensing/keys.py` — RSA key generation, license signing/validation |
| 2 | Create `licensing/plans.py` — plan-to-feature mapping |
| 3 | Create `middleware/license.py` — inject plan/features into request state |
| 4 | Create `licensing/offline.py` — offline license file validator |
| 5 | Add `@require_feature()` decorator, apply to existing endpoints |
| 6 | Add license key entry page to Admin UI |
| 7 | Ensure Free tier default when no license configured |

**Verification:** No license = Free tier works fully. Pro license key unlocks clustering/sub-agents.

### Phase 7C: Stripe Billing (3-4 days)

| Step | Task |
|---|---|
| 1 | Create `billing/subscriptions.py` — Stripe subscription management |
| 2 | Create `billing/webhooks.py` — idempotent webhook handler |
| 3 | Create `billing/usage.py` — credit metering + Stripe usage records |
| 4 | Create `middleware/credits.py` — credit checking + deduction |
| 5 | Create `routers/billing.py` — REST endpoints for billing operations |
| 6 | Admin UI Billing page (usage dashboard, plan info, Stripe Portal link) |
| 7 | Wire credit deduction into `agent_runner.py` and `models/router.py` |

**Verification:** Stripe subscription upgrade → features unlocked. Usage metered correctly. Grace period on payment failure.

### Phase 7D: Plugin Marketplace (4-5 days)

| Step | Task |
|---|---|
| 1 | Define `nexus-plugin.yaml` manifest format |
| 2 | Create `marketplace/registry.py` — plugin metadata, versions, search |
| 3 | Create `marketplace/installer.py` — download, verify signature, install |
| 4 | Create `marketplace/reviewer.py` — automated security checks |
| 5 | Create `marketplace/billing.py` — Stripe Connect for developer payouts |
| 6 | Update `plugins/manager.py` — load marketplace plugins from separate dir |
| 7 | Admin UI Marketplace page (browse, install, manage) |
| 8 | `nexus-plugin-sdk` package scaffolding (init, test, package, publish CLI) |

**Verification:** Install a test plugin from marketplace → tools appear in Nexus → usage metered.

### Phase 7E: Enterprise Auth (3-4 days)

| Step | Task |
|---|---|
| 1 | Keycloak integration — OIDC client, realm setup guide |
| 2 | SAML support via Keycloak Identity Brokering |
| 3 | SCIM provisioning endpoint (user sync from enterprise IdP) |
| 4 | Per-org SSO configuration in Admin UI |
| 5 | Signed license file generation endpoint (for on-prem customers) |
| 6 | Air-gapped deployment guide (offline license + bundled dependencies) |
| 7 | Organization admin dashboard (members, roles, SSO status) |

**Verification:** Enterprise customer's Azure AD SSO works via Keycloak. Offline license validates without internet.

---

## 11. Usage Dashboard Design

### Key Metrics to Surface

```
┌─────────────────────────────────────────────────────┐
│  Credits Used: 23,450 / 50,000          [====--]    │
│  Projected: ~38,000 by month end                    │
├─────────────────────────────────────────────────────┤
│  Cost Breakdown This Month                          │
│  ┌────────────┬────────┬──────────┐                 │
│  │ Ollama     │ 1,240  │ $0.00    │  (local=free)   │
│  │ Claude     │ 18,400 │ $18.40   │                 │
│  │ Sub-agents │ 3,200  │ $3.20    │                 │
│  │ Plugins    │ 610    │ $0.61    │                 │
│  │ TOTAL      │ 23,450 │ $22.21   │  (within plan)  │
│  └────────────┴────────┴──────────┘                 │
├─────────────────────────────────────────────────────┤
│  Daily Usage (bar chart, last 30 days)              │
│  ████ ██████ ████████ ██████ ████ ███████           │
├─────────────────────────────────────────────────────┤
│  Alerts: ⚠️ Set at 80% and 100% of monthly credits  │
│  [Configure Alerts]  [View Invoices]  [Manage Plan] │
└─────────────────────────────────────────────────────┘
```

---

## 12. Security Considerations

- **License keys:** RSA-2048 signed. Public key embedded in binary. Private key on licensing server only
- **API keys:** SHA-256 hashed in DB, never stored plaintext. Rotatable, revocable
- **Stripe webhooks:** Signature verification on every webhook (`stripe.Webhook.construct_event`)
- **Plugin signatures:** Ed25519 signed manifests + Nexus marketplace co-signature
- **Offline licenses:** Grace periods, not hard locks. Cannot be forged without private key
- **Anti-piracy philosophy:** Make compliance easy (fair pricing). Rapid feature velocity is the best anti-piracy (pirates get a snapshot, customers get continuous updates)
- **Data handling:** License tier never affects data retention negatively. Downgrade = feature restriction, never data deletion

---

## 13. Open Questions

1. **Pricing validation:** Is $49/mo Pro right? Need market research on competing AI agent platforms
2. **Annual discounts:** 2 months free (17% off) standard enough?
3. **Keycloak vs Ory:** Keycloak is heavier (Java) but more enterprise-ready. Ory is lighter (Go) but needs SAML bridge. Customer feedback needed
4. **Plugin SDK language:** Python-only initially? TypeScript SDK for broader developer appeal?
5. **Marketplace hosting:** Self-hosted marketplace registry, or third-party (e.g., Cloudsmith, Artifactory)?
6. **SOC2/HIPAA:** Enterprise customers may need compliance certifications. Timeline and cost for SOC2 Type II?
7. **White-label licensing:** Allow enterprises to rebrand Nexus? Adds revenue but complexity
8. **Metered vs included credits:** Should Pro include any Claude API credits, or charge purely on usage?
9. **Free tier conversation limit:** 100/month may be too low or too high. A/B test needed
10. **Trial duration:** 14 days standard, but AI tools may need longer to demonstrate value (30 days?)

---

## 14. Relationship to Phase 6 (Clustering)

Phase 7 naturally follows Phase 6 because:

1. **Clustering defines tiers** — single agent (Free) vs clustered (Pro/Enterprise) is the primary feature gate
2. **Redis is already deployed** — credit ledger, rate limiting, license caching can ride Redis
3. **Agent count = seat count** — clustering's agent registry is the natural billing anchor
4. **Sub-agents gated** — the orchestration system (Phase 4) becomes a Pro feature
5. **Plugin marketplace needs stable infrastructure** — clustering provides the scalable backend

```
Phase 6: Clustering  →  Phase 7A: Auth  →  Phase 7B: License  →  Phase 7C: Billing
                                                                        ↓
                                            Phase 7E: Enterprise  ←  Phase 7D: Marketplace
```

---

## 15. Key Principles

1. **Free tier must be genuinely useful.** A single Ollama-powered agent with core plugins is a compelling product. Free users become advocates and convert.

2. **Never lock out paying customers.** Payment failure = grace period → downgrade. Never delete data.

3. **Local-first licensing.** Self-hosted deployments work offline with signed license files. No mandatory phone-home.

4. **Charge for cloud, not local.** Ollama usage is always free (user's compute). Credits only apply to cloud model APIs.

5. **Marketplace grows the pie.** Zero commission Year 1. The plugin ecosystem's value to customers justifies subscription pricing.

6. **Enterprise is high-touch.** SSO, on-prem, compliance, and dedicated support justify 5-10x pricing over Pro.

7. **Configuration over code.** Plan-to-feature mapping is data (PLAN_FEATURES dict), not scattered `if pro:` checks throughout the codebase.
