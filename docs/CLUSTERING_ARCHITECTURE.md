# Nexus Agent Clustering Architecture

## Enterprise-Grade Primary/Secondary Agent Clustering with Redis

**Status:** Architecture Draft (Feb 13, 2026)
**Target:** Post-weekend build (Week of Feb 17, 2026)
**Narrative:** "Nexus-Inside" Enterprise Autonomous Agent Platform

---

## 1. Vision

Transform Nexus from a single-agent system into a horizontally scalable, fault-tolerant **agent cluster** where multiple Nexus instances coordinate work, share memory, and fail over automatically. This is the foundation for the enterprise "Nexus-Inside" offering.

### What Changes
| Today (Single Agent) | Tomorrow (Agent Cluster) |
|---|---|
| One Nexus process handles everything | Primary orchestrates, Secondaries execute |
| asyncio task queue (no persistence) | Redis Streams (durable, distributed) |
| PostgreSQL-only memory | PostgreSQL (cold) + Redis (hot) + optional graph |
| Failover = restart process | Failover = automatic promotion in <5s |
| One Ollama + one Claude connection | N agents, each with own model connections |
| Sub-agents are in-process coroutines | Sub-agents are independent Nexus instances |

### What Stays the Same
- PostgreSQL remains the durable system of record
- Plugin system, skill engine, tool ecosystem unchanged
- Chat UI, Admin UI, Telegram interfaces unchanged (they connect to the cluster load balancer)
- Local-first model routing (Ollama primary, Claude fallback) unchanged per-agent

---

## 2. Architecture Overview

```
                    ┌─────────────────────────────────────┐
                    │          Client Layer                │
                    │  Chat UI  │  Admin UI  │  Telegram   │
                    └─────────────┬───────────────────────┘
                                  │
                    ┌─────────────▼───────────────────────┐
                    │       Load Balancer / Gateway        │
                    │   (nginx / HAProxy / Traefik)        │
                    │   Session-affinity by conv_id        │
                    └──┬──────────┬───────────────┬───────┘
                       │          │               │
              ┌────────▼──┐  ┌───▼────────┐  ┌───▼────────┐
              │  Primary   │  │ Secondary  │  │ Secondary  │
              │  Agent     │  │ Agent A    │  │ Agent B    │
              │            │  │            │  │            │
              │ Orchestr.  │  │ Worker     │  │ Worker     │
              │ Router     │  │ Builder    │  │ Researcher │
              │ Planner    │  │ Reviewer   │  │ Verifier   │
              └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
                    │               │               │
         ┌──────────▼───────────────▼───────────────▼──────┐
         │              Redis Cluster                       │
         │                                                  │
         │  ┌─────────┐  ┌──────────┐  ┌────────────────┐  │
         │  │ Streams  │  │ Pub/Sub  │  │ Working Memory │  │
         │  │ (tasks)  │  │ (events) │  │ (session JSON) │  │
         │  └─────────┘  └──────────┘  └────────────────┘  │
         │                                                  │
         │  ┌───────────────┐  ┌──────────────────────┐    │
         │  │ Vector Index   │  │ Agent Registry       │    │
         │  │ (RediSearch)   │  │ (Hash: agent:{id})   │    │
         │  └───────────────┘  └──────────────────────┘    │
         └─────────────────────────┬───────────────────────┘
                                   │
         ┌─────────────────────────▼───────────────────────┐
         │              PostgreSQL                          │
         │  Conversations │ Work Items │ Config │ Audit     │
         │  Long-term Memory │ User Prefs │ Skills          │
         └─────────────────────────────────────────────────┘

         ┌─────────────────────────────────────────────────┐
         │          Graph Store (Optional, Phase 2)         │
         │  Neo4j / FalkorDB — Entity relationships         │
         └─────────────────────────────────────────────────┘
```

---

## 3. Core Components

### 3.1 Agent Registry

Every Nexus agent instance registers in Redis on startup and maintains a heartbeat.

**Redis Key:** `nexus:agent:{agent_id}` (Hash)

```
Fields:
  id:           "nexus-primary-01"
  role:         "primary" | "secondary" | "standby"
  status:       "active" | "draining" | "failed" | "starting"
  host:         "10.0.1.10"
  port:         8080
  models:       '["ollama/kimi-k2.5", "claude/sonnet-4"]'
  capabilities: '["orchestration", "web", "terminal", "github"]'
  current_load: 3          # active conversations
  max_load:     20         # capacity
  last_heartbeat: 1739456789
  started_at:   1739450000
  config_epoch: 42         # monotonically increasing topology version
```

**Heartbeat:** Every 2 seconds via `HSET nexus:agent:{id} last_heartbeat {timestamp}`.
**Failure Detection:** Agent missed 3 consecutive heartbeats (6s) = SDOWN. Quorum of agents agree = ODOWN. Triggers failover.

**Implementation:** New module `backend/core/cluster/registry.py`

### 3.2 Task Distribution (Redis Streams)

Replace the in-process asyncio task queue with Redis Streams for durable, distributed task distribution.

**Stream:** `nexus:tasks:{priority}` (high, normal, low)

```
Message fields:
  task_id:      "task_abc123"
  type:         "conversation" | "sub_agent" | "skill" | "plan_step" | "reminder"
  conv_id:      "conv_xyz"
  user_id:      "user_001"
  prompt:        "Research management accounting best practices"
  model_hint:   "ollama"        # preferred model, not mandatory
  parent_id:    "orch_456"      # parent orchestration if sub-agent
  role:         "researcher"    # sub-agent role
  max_tokens:   4096
  timeout_ms:   60000
  created_at:   1739456789
```

**Consumer Group:** `nexus:workers`
- Each Secondary agent is a consumer in the group
- Claims messages via `XREADGROUP`, processes, then `XACK`
- Unclaimed messages after timeout are auto-reassigned (pending entries list)
- Primary can also consume for lightweight tasks

**Dead Letter:** Failed tasks after 3 attempts move to `nexus:tasks:dead` for inspection.

**Implementation:** New module `backend/core/cluster/task_stream.py`, replaces `backend/tasks/queue.py` when clustering enabled

### 3.3 Working Memory (Redis JSON)

Hot session state in Redis for sub-millisecond cross-agent access.

**Key:** `nexus:session:{conv_id}` (JSON with TTL)

```json
{
  "conv_id": "conv_xyz",
  "user_id": "user_001",
  "owner_agent": "nexus-primary-01",
  "model": "ollama/kimi-k2.5",
  "messages_count": 15,
  "recent_messages": [/* last 5 messages for quick context */],
  "active_tools": ["web_fetch", "terminal_execute"],
  "memory_context": "User prefers concise responses. Working on Nexus project.",
  "sub_agents": {
    "researcher_01": {"status": "running", "model": "ollama"},
    "reviewer_01": {"status": "completed", "output_key": "nexus:result:rev_01"}
  },
  "token_estimate": 8500,
  "ttl_seconds": 3600,
  "updated_at": 1739456789
}
```

**Promotion Pipeline:**
1. Session active → Working Memory in Redis (hot)
2. Session idle >1hr → Promote to PostgreSQL (cold), extract memories
3. Key facts/preferences → Long-term vector memory (Redis + PostgreSQL)

**Implementation:** New module `backend/core/cluster/working_memory.py`

### 3.4 Event Bus (Redis Pub/Sub)

Real-time broadcast for coordination signals that don't need durability.

**Channels:**
| Channel | Purpose | Example |
|---------|---------|---------|
| `nexus:events:agent` | Agent lifecycle | `{"type":"agent_joined", "id":"nexus-sec-03", "capabilities":[...]}` |
| `nexus:events:model` | Model status changes | `{"type":"model_switch", "conv_id":"xyz", "from":"ollama", "to":"claude"}` |
| `nexus:events:abort` | Abort signals | `{"type":"abort", "conv_id":"xyz", "reason":"user_cancelled"}` |
| `nexus:events:config` | Config propagation | `{"type":"config_update", "key":"OLLAMA_MODEL", "epoch":43}` |
| `nexus:events:health` | Health alerts | `{"type":"agent_sdown", "id":"nexus-sec-02", "missed_heartbeats":3}` |

**Implementation:** New module `backend/core/cluster/event_bus.py`

### 3.5 Semantic Memory Layer (RediSearch)

Shared vector index for cross-agent memory search. Any agent can retrieve context from any conversation.

**Index:** `nexus:memory:vectors`

```
Schema:
  id:         TEXT (memory ID)
  text:       TEXT (original content)
  embedding:  VECTOR (HNSW, 1536 dims, cosine distance)
  user_id:    TAG
  conv_id:    TAG
  agent_id:   TAG
  memory_type: TAG (preference | fact | project | pattern | goal)
  topics:     TAG (comma-separated)
  created_at: NUMERIC
  confidence: NUMERIC
```

**Deduplication:** Three-stage (matching Redis Agent Memory Server pattern):
1. ID-based (skip if exists)
2. Hash-based (SHA256 of content)
3. Semantic (vector similarity < 0.12 distance → LLM-assisted merge)

**Implementation:** New module `backend/core/cluster/memory_index.py`, extends `PersonalMemorySystem`

### 3.6 Primary Election & Failover

Inspired by Redis Sentinel's two-phase detection + Redis Cluster's election protocol.

**Normal Operation:**
- One Primary agent orchestrates: routes conversations, spawns sub-agent tasks, manages plans
- N Secondary agents execute: process tasks from Streams, report results back
- All agents heartbeat to Redis and participate in failure detection

**Failover Protocol:**
```
1. DETECTION (any agent)
   - Agent A notices Primary missed 3 heartbeats → marks SDOWN
   - Agent A publishes SDOWN to nexus:events:health

2. CONSENSUS (quorum)
   - When (N/2 + 1) agents agree on SDOWN → escalate to ODOWN
   - Quorum check via Redis sorted set: nexus:failover:votes

3. ELECTION
   - Eligible secondaries (status=active, load < max) compete
   - Priority: lowest (config_epoch_lag * 1000 + current_load)
     → Most up-to-date, least loaded wins
   - Winner increments config_epoch, sets role=primary

4. PROMOTION (winning secondary)
   - Publishes "primary_elected" event with new config_epoch
   - Takes ownership of unassigned conversations
   - Reassigns pending tasks from old primary's consumer
   - All agents update routing tables to new primary

5. RECOVERY (old primary comes back)
   - Detects higher config_epoch → demotes self to secondary
   - Joins consumer group as worker
   - Syncs missed state from Redis working memory
```

**Split-Brain Prevention:**
- Fencing token: `config_epoch` — all writes include epoch, stale-epoch writes rejected
- `min-secondaries-to-accept-work`: Primary stops accepting new conversations if fewer than 1 secondary is reachable (like Redis's `min-replicas-to-write`)

**Implementation:** New module `backend/core/cluster/election.py`

---

## 4. Data Flow

### 4.1 Conversation Request (Clustered)

```
User sends message via Chat UI WebSocket
    │
    ▼
Load Balancer (session affinity by conv_id)
    │
    ▼
Primary Agent receives request
    │
    ├─ Simple query (no tools, short context)
    │   └─ Primary handles directly (Ollama/Claude)
    │       └─ Result → Redis working memory + PostgreSQL + WebSocket
    │
    ├─ Complex query (multi-tool, research)
    │   └─ Primary creates task(s) in Redis Streams
    │       └─ Secondary claims task → processes → XACK
    │           └─ Result → Redis working memory
    │               └─ Primary synthesizes → WebSocket
    │
    └─ Multi-agent orchestration (/multi)
        └─ Primary creates SubAgentSpecs → task per spec in Streams
            └─ Secondaries claim by role (Builder, Researcher, etc.)
                └─ Dependency layers honored via task dependencies
                    └─ Final synthesis by Primary → WebSocket
```

### 4.2 Sub-Agent Evolution

Today's `sub_agent.py` runs sub-agents as in-process `AgentAttempt` coroutines. In clustering mode, sub-agents become distributed tasks:

```python
# Today (single process)
async def execute(self, orchestration):
    for layer in dependency_layers:
        results = await asyncio.gather(*[self._run_sub_agent(spec) for spec in layer])

# Tomorrow (distributed)
async def execute(self, orchestration):
    for layer in dependency_layers:
        # Publish tasks to Redis Streams
        task_ids = [await task_stream.publish(spec) for spec in layer]
        # Wait for all results (with timeout)
        results = await task_stream.await_results(task_ids, timeout=60)
```

The `SubAgentOrchestrator` still lives on the Primary — only the execution is distributed.

---

## 5. Configuration

### 5.1 New Settings (DB-backed via ConfigManager)

```python
# Clustering
CLUSTER_ENABLED = False              # Feature flag — false = single-agent mode (backwards compatible)
CLUSTER_ROLE = "auto"                # "primary", "secondary", "auto" (auto-elects)
CLUSTER_AGENT_ID = ""                # Auto-generated UUID if empty
CLUSTER_MAX_LOAD = 20                # Max concurrent conversations per agent

# Redis
REDIS_URL = "redis://localhost:6379" # Single node or cluster seed
REDIS_PASSWORD = ""                  # Encrypted in DB
REDIS_TLS = False                    # Enable TLS for production
REDIS_KEY_PREFIX = "nexus:"          # Namespace isolation for multi-tenant

# Failover
CLUSTER_HEARTBEAT_INTERVAL = 2      # Seconds between heartbeats
CLUSTER_FAILURE_THRESHOLD = 3        # Missed heartbeats = SDOWN
CLUSTER_ELECTION_TIMEOUT = 5         # Seconds to wait for election consensus
CLUSTER_MIN_SECONDARIES = 1          # Primary stops accepting work below this

# Memory
CLUSTER_WORKING_MEMORY_TTL = 3600    # Session TTL in Redis (seconds)
CLUSTER_VECTOR_DIMS = 1536           # Embedding dimensions
CLUSTER_MEMORY_PROMOTION_DELAY = 300 # Seconds before promoting to long-term
```

### 5.2 Backwards Compatibility

When `CLUSTER_ENABLED = False` (default):
- Everything works exactly as today
- asyncio task queue, in-process sub-agents, PostgreSQL-only memory
- Zero Redis dependency
- No behaviour change for existing single-node deployments

When `CLUSTER_ENABLED = True`:
- Redis connection required
- Agent registers in cluster
- Task queue switches to Redis Streams
- Working memory layer activates
- Sub-agents distributed to cluster workers

---

## 6. New Files & Modules

```
backend/
├── core/
│   └── cluster/                    # NEW — all clustering logic
│       ├── __init__.py             # Cluster manager (init/shutdown, feature flag check)
│       ├── registry.py             # Agent registration, heartbeat, discovery
│       ├── task_stream.py          # Redis Streams task distribution
│       ├── working_memory.py       # Session state in Redis JSON
│       ├── event_bus.py            # Pub/Sub event broadcasting
│       ├── memory_index.py         # RediSearch vector memory
│       ├── election.py             # Primary election & failover protocol
│       └── health.py               # Health monitoring, SDOWN/ODOWN detection
│
├── plugins/
│   └── mem0_plugin.py              # MODIFY — option to use Redis backend instead of cloud
│
├── tasks/
│   └── queue.py                    # MODIFY — delegate to task_stream when clustered
│
├── core/
│   ├── sub_agent.py                # MODIFY — distributed execution via Streams
│   ├── agent_runner.py             # MODIFY — cluster-aware routing
│   └── work_registry.py            # MODIFY — cross-agent work tracking
│
└── requirements.txt                # ADD — redis[hiredis], redisvl
```

### Dependencies to Add

```
# Redis client + performance boost
redis[hiredis]>=5.0.0

# Redis vector library (RediSearch integration)
redisvl>=0.3.0
```

---

## 7. Implementation Phases

### Phase 6A: Redis Foundation (2-3 days)

**Goal:** Redis connected, agent registry, event bus. No behaviour change yet.

| Step | Task | Files |
|------|------|-------|
| 1 | Add `redis[hiredis]`, `redisvl` to requirements | `requirements.txt` |
| 2 | Create `cluster/__init__.py` — ClusterManager with feature flag, Redis connection pool | `core/cluster/__init__.py` |
| 3 | Create `registry.py` — register, heartbeat loop, discovery | `core/cluster/registry.py` |
| 4 | Create `event_bus.py` — publish/subscribe wrapper | `core/cluster/event_bus.py` |
| 5 | Wire into `app.py` lifespan (init if CLUSTER_ENABLED, shutdown gracefully) | `app.py` |
| 6 | Add cluster settings to ConfigManager | `config_manager.py` |
| 7 | Admin UI — Cluster status page (agent list, health, roles) | `admin-ui/src/pages/cluster.tsx` |

**Verification:** Start 2 Nexus instances, both appear in Redis registry, heartbeats visible in Admin UI.

### Phase 6B: Distributed Task Queue (2-3 days)

**Goal:** Sub-agents and tasks execute on remote agents via Redis Streams.

| Step | Task | Files |
|------|------|-------|
| 1 | Create `task_stream.py` — publish, consume, acknowledge, dead letter | `core/cluster/task_stream.py` |
| 2 | Create consumer worker loop (claims tasks, runs AgentAttempt, ACKs) | `core/cluster/task_stream.py` |
| 3 | Update `sub_agent.py` — distributed execution when clustered | `core/sub_agent.py` |
| 4 | Update `queue.py` — delegate to task_stream when clustered | `tasks/queue.py` |
| 5 | Task timeout + reassignment logic | `core/cluster/task_stream.py` |
| 6 | WorkRegistry hooks for distributed tasks | `core/work_registry.py` |
| 7 | Admin UI — Task stream dashboard (pending, processing, completed, dead) | `admin-ui/src/pages/cluster.tsx` |

**Verification:** Send `/multi` command → tasks appear in Redis Stream → Secondary picks them up → results flow back to Primary → user sees synthesized response.

### Phase 6C: Working Memory & Vector Index (2-3 days)

**Goal:** Shared session state + semantic memory across all agents.

| Step | Task | Files |
|------|------|-------|
| 1 | Create `working_memory.py` — session CRUD in Redis JSON | `core/cluster/working_memory.py` |
| 2 | Create `memory_index.py` — RediSearch vector index, semantic search | `core/cluster/memory_index.py` |
| 3 | Memory promotion pipeline (working → long-term) | `core/cluster/memory_index.py` |
| 4 | Deduplication (ID, hash, semantic) | `core/cluster/memory_index.py` |
| 5 | Wire into PassiveMemorySystem — dual-write to PG + Redis | `storage/memory_system.py` |
| 6 | Update Mem0 plugin — option for Redis backend | `plugins/mem0_plugin.py` |
| 7 | Cross-agent memory search tool | `plugins/brave_browser_plugin.py` or new plugin |

**Verification:** Agent A stores memory from conversation → Agent B can retrieve it via semantic search. Session state visible across agents.

### Phase 6D: Election & Failover (2-3 days)

**Goal:** Automatic primary election and failover with zero downtime.

| Step | Task | Files |
|------|------|-------|
| 1 | Create `health.py` — SDOWN/ODOWN detection, quorum voting | `core/cluster/health.py` |
| 2 | Create `election.py` — election protocol, promotion, demotion | `core/cluster/election.py` |
| 3 | Fencing with config_epoch | `core/cluster/election.py` |
| 4 | Split-brain prevention (min-secondaries check) | `core/cluster/election.py` |
| 5 | Task reassignment on failover (pending entries list) | `core/cluster/task_stream.py` |
| 6 | Conversation ownership transfer | `core/cluster/working_memory.py` |
| 7 | Integration test — kill primary, verify secondary promotes in <5s | `tests/test_cluster_failover.py` |

**Verification:** Kill Primary process → Secondary detects failure → Elects self → Takes over conversations → User experiences <5s interruption → Old Primary restarts as Secondary.

### Phase 6E: Production Hardening (2-3 days)

**Goal:** TLS, monitoring, load balancing, deployment automation.

| Step | Task | Files |
|------|------|-------|
| 1 | Redis TLS configuration | `core/cluster/__init__.py` |
| 2 | Prometheus metrics export (agent count, task throughput, memory usage, failover events) | `core/cluster/metrics.py` |
| 3 | Load balancer configuration (nginx/HAProxy with session affinity) | `deploy/` |
| 4 | Docker Compose for multi-agent development | `docker-compose.cluster.yml` |
| 5 | Graceful drain — Primary/Secondary can be removed without dropping work | `core/cluster/registry.py` |
| 6 | Rate limiting across cluster (distributed rate limiter in Redis) | `plugins/base.py` |
| 7 | Comprehensive test suite | `tests/test_cluster_*.py` |

---

## 8. Capacity Planning

### Minimum Viable Cluster
```
1x Primary Agent    (orchestration + light work)
2x Secondary Agents (workers)
1x Redis instance   (can be Redis Cloud or self-hosted)
1x PostgreSQL       (existing)
─────────────────
Total: 4 processes + existing DB
```

### Enterprise Scale
```
1x Primary Agent + 1x Hot Standby
N Secondary Agents (auto-scale by load)
3x Redis Cluster nodes (sharded, HA)
2x PostgreSQL (primary + read replica)
1x Neo4j (optional, graph memory)
1x Load Balancer (nginx/HAProxy/Traefik)
─────────────────
Scale: 50+ concurrent conversations, <100ms p99 response start
```

### Resource Estimates
| Component | CPU | RAM | Disk |
|-----------|-----|-----|------|
| Primary Agent | 2 cores | 4GB | 1GB |
| Secondary Agent | 2 cores | 4GB | 1GB |
| Redis (single) | 1 core | 2GB | 1GB |
| Redis Cluster (3-node) | 3 cores | 6GB | 3GB |
| Ollama (per agent) | 4 cores + GPU | 16GB | 20GB (model) |

---

## 9. Migration Path

### From Single-Agent to Cluster

```
Step 1: Install Redis (brew install redis / docker)
Step 2: Set CLUSTER_ENABLED=True, REDIS_URL in Admin UI
Step 3: Restart Nexus → auto-registers as Primary (only agent)
Step 4: Start second Nexus instance with CLUSTER_ROLE=secondary
        → Auto-discovers Primary via Redis registry
Step 5: Verify in Admin UI → Cluster page shows both agents
Step 6: Test with /multi → tasks distributed to Secondary
```

**Zero-downtime migration:** The feature flag means existing deployments don't change. Clustering is opt-in. When enabled, the system gracefully upgrades — single agent becomes Primary, new instances join as Secondaries.

---

## 10. Security Considerations

- **Redis AUTH:** Required in production. ACL with minimal permissions per agent role
- **TLS:** All Redis connections encrypted (client, replication, cluster bus)
- **Network isolation:** Redis on private network, not internet-facing
- **Secret management:** Redis password encrypted in DB via ConfigManager (same as other secrets)
- **Agent authentication:** Each agent has a unique ID + shared cluster secret for mutual auth
- **Fencing tokens:** config_epoch prevents stale agents from making authoritative decisions
- **Audit trail:** All task claims, completions, and failovers logged to PostgreSQL

---

## 11. Monitoring & Observability

### Key Metrics
| Metric | Source | Alert Threshold |
|--------|--------|-----------------|
| `nexus_cluster_agents_total` | Registry | < min_secondaries |
| `nexus_cluster_agent_load` | Registry | > 80% max_load |
| `nexus_tasks_pending` | Streams | > 100 (backlog) |
| `nexus_tasks_dead` | Dead letter | > 0 (failed tasks) |
| `nexus_failover_total` | Election | > 1/hour (instability) |
| `nexus_memory_promotion_lag` | Working Memory | > 600s |
| `nexus_redis_latency_ms` | Redis | > 10ms (p99) |
| `nexus_heartbeat_missed` | Health | > 2 consecutive |

### Admin UI Cluster Page
- Agent topology view (Primary/Secondary roles, status dots)
- Task stream dashboard (pending/processing/completed/dead counts, throughput)
- Memory utilization (Redis working memory, vector index size)
- Failover history log
- Per-agent load and model status

---

## 12. Open Questions

1. **Embedding model:** Use OpenAI `text-embedding-3-small` (1536 dims, cloud) or a local model via Ollama? Trade-off: quality vs. self-contained
2. **Graph memory (Phase 2):** Neo4j vs FalkorDB vs Kuzu? Neo4j most mature but heaviest. FalkorDB is Redis-compatible. Kuzu is embedded (no extra process)
3. **Multi-tenant:** Do we namespace by `user_id` or support multiple tenants per cluster? Affects key prefix strategy
4. **Ollama sharing:** Can multiple agent instances share one Ollama server, or does each need its own? Ollama's concurrency model needs testing
5. **Claude API rate limits:** With N agents all potentially failing over to Claude, need coordinated rate limit tracking in Redis
6. **WebSocket routing:** When Primary fails over, how do existing WebSocket connections migrate? Options: client reconnect, proxy-level redirect, or connection drain + re-establish

---

## 13. Dependencies & Prerequisites

- **Redis 7.2+** (for JSON, Streams, RediSearch, ACLs)
- **Python packages:** `redis[hiredis]>=5.0.0`, `redisvl>=0.3.0`
- **Existing Nexus systems:** All Phase 3-5 features working (sub-agents, work registry, web understanding)
- **Testing:** Docker for spinning up multi-agent test environments
- **Optional:** Redis Cloud account for managed deployment (auto-scaling, backups, TLS by default)
