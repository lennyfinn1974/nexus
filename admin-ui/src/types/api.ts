// ── Settings ──
export interface SettingSchema {
  key: string
  label: string
  type: 'text' | 'password' | 'number' | 'select' | 'range' | 'textarea'
  category: string
  description: string
  encrypted: boolean
  value: string
  has_value: boolean
  options?: string[]
  min?: number
  max?: number
}

export interface SettingsResponse {
  settings: SettingSchema[]
}

export interface SettingsUpdateResponse {
  updated: string[]
  count: number
  message: string
}

export interface TestConnectionResponse {
  success: boolean
  message?: string
  error?: string
}

// ── Models ──
export interface ModelsResponse {
  ollama_model: string
  ollama_base_url: string
  ollama_available: boolean
  claude_model: string
  claude_available: boolean
  claude_code_available: boolean
  claude_code_model: string | null
  claude_code_enabled: boolean
  complexity_threshold: number
  // Sub-agent settings
  sub_agent_enabled?: boolean
  sub_agent_auto_enabled?: boolean
  sub_agent_max_concurrent?: number
  sub_agent_cc_concurrent?: number
  sub_agent_builder_model?: string
  sub_agent_reviewer_model?: string
  sub_agent_timeout?: number
}

export interface OllamaModel {
  name: string
  size: number
  modified: string
}

export interface OllamaListResponse {
  success: boolean
  models: OllamaModel[]
  error?: string
}

// ── Plugins ──
export interface PluginTool {
  name: string
  description: string
  parameters: Record<string, unknown>
}

export interface PluginCommand {
  command: string
  description: string
}

export interface ActivePlugin {
  name: string
  description: string
  version: string
  enabled: boolean
  health: { status: string; message?: string }
  tools: PluginTool[]
  commands: PluginCommand[]
  required_settings: Record<string, string>
  pip_requires: string[]
}

export interface AvailablePlugin {
  name: string
  file: string
  enabled: boolean
  reason: string
}

export interface PluginsResponse {
  active: ActivePlugin[]
  available: AvailablePlugin[]
}

// ── Status ──
export interface ModelStatus {
  ollama_available: boolean
  claude_available: boolean
  claude_code_available: boolean
  ollama_model: string
  claude_model: string
  claude_code_model: string | null
}

export interface StatusResponse {
  models: ModelStatus
  tasks_active: number
  skills_count: number
  plugins: Record<string, { enabled: boolean; version: string; tools: number; commands: number }>
}

// ── Health ──
export interface HealthCheck {
  status: string
  details?: string
  [key: string]: unknown
}

export interface HealthResponse {
  healthy: boolean
  timestamp: number
  checks: {
    database: HealthCheck
    models: HealthCheck & { claude?: string; ollama?: string; claude_code?: string }
    plugins: HealthCheck & { total?: number; errors?: number }
    filesystem: HealthCheck
    memory: HealthCheck & { usage_percent?: number; available_mb?: number }
  }
}

// ── Usage ──
export interface UsageDailyEntry {
  model_used: string
  message_count: number
  total_tokens_in: number
  total_tokens_out: number
  day: string
}

export interface UsageTotalEntry {
  model_used: string
  message_count: number
  total_tokens_in: number
  total_tokens_out: number
}

export interface UsageResponse {
  daily: UsageDailyEntry[]
  totals: UsageTotalEntry[]
}

// ── Conversations ──
export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

// ── Tasks ──
export interface Task {
  id: string
  type: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  created_at: string
  started_at?: string
  completed_at?: string
  result?: string
  error?: string
}

// ── Work Items ──
export interface WorkItem {
  id: string
  kind: 'agent' | 'sub_agent' | 'plan' | 'plan_step' | 'task' | 'reminder' | 'orchestration'
  title: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  parent_id: string | null
  conv_id: string | null
  model: string | null
  metadata: Record<string, unknown> | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface WorkItemCounts {
  pending: number
  running: number
  completed: number
  failed: number
  cancelled: number
  total: number
}

// ── Audit ──
export interface AuditEntry {
  id: number
  key: string
  old_value: string | null
  new_value: string | null
  changed_at: string
  changed_by: string
}

// ── System ──
export interface SystemInfo {
  python_version: string
  platform: string
  base_dir: string
  skills_dir: string
  docs_dir: string
  data_dir: string
  db_path: string
  db_size_mb: number
  skills_count: number
}

export interface Backup {
  file: string
  size_mb: number
  created: string
}

export interface BackupResponse {
  path: string
  size_mb: number
  timestamp: string
}

// ── System Prompt ──
export interface SystemPromptResponse {
  base_prompt: string
  plugin_additions: string
  full_prompt: string
}

// ── Logs ──
export interface LogEntry {
  ts: string
  level: string
  name: string
  msg: string
}

// ── Skills ──
export interface Skill {
  id: string
  name: string
  type: string
  domain: string
  description: string
  version?: string
  usage_count?: number
}

export interface SkillPack {
  id: string
  name: string
  type: string
  description: string
  domain: string
  version: string
  config_keys: string[]
  installed: boolean
}

// ── Catalog ──
export interface CatalogEntry {
  id: string
  name: string
  description: string
  category: string
  source: string
  size_kb: number
  installed: boolean
}

export interface CatalogSearchResponse {
  results: CatalogEntry[]
  total: number
}

export interface CatalogCategory {
  category: string
  count: number
}

export interface CatalogInstallResponse {
  success: boolean
  message: string
  skill_id: string
  name: string
}

// ── Cluster ──
export interface ClusterAgent {
  id: string
  role: 'primary' | 'secondary' | 'standby' | 'unknown'
  status: 'active' | 'starting' | 'draining' | 'stopped' | 'failed' | 'unknown'
  host: string
  port: number
  models: string[]
  capabilities: string[]
  current_load: number
  max_load: number
  last_heartbeat: number
  started_at: number
  config_epoch: number
  is_self?: boolean
  healthy?: boolean
  heartbeat_age_seconds?: number
  missed_heartbeats?: number
}

export interface EventBusStats {
  published: number
  received: number
  errors: number
  handler_count: number
  channels_with_handlers: string[]
}

export interface TaskStreamInfo {
  high?: { length: number; pending: number }
  normal?: { length: number; pending: number }
  low?: { length: number; pending: number }
  dead_letter?: { length: number }
}

export interface TaskStreamStats {
  published: number
  consumed: number
  completed: number
  failed: number
  dead_lettered: number
  handler_types: string[]
}

export interface WorkingMemoryStats {
  reads: number
  writes: number
  promotions: number
  evictions: number
  promotion_queue_size: number
  active_sessions: number
}

export interface MemoryIndexStats {
  stored: number
  searched: number
  duplicates_found: number
  index_available: boolean
  vector_dims: number
  total_memories: number
  memory_types: Record<string, number>
}

export interface HealthMonitorStatus {
  checks: number
  sdown_events: number
  odown_events: number
  sdown_agents: string[]
  odown_agents: string[]
  votes: Record<string, { votes: number; voters: string[]; odown: boolean; sdown_since: number }>
}

export interface ElectionStatus {
  election_in_progress: boolean
  last_election_time: number
  elections_won: number
  elections_lost: number
  demotions: number
  min_secondaries_met: boolean
}

export interface ClusterStatusResponse {
  enabled: boolean
  active: boolean
  agent_id: string | null
  role: string | null
  agents: ClusterAgent[]
  agent_count: number
  primary_id?: string | null
  redis_connected: boolean
  redis_url?: string
  config_epoch?: number
  event_bus?: EventBusStats
  task_streams?: TaskStreamInfo
  task_stats?: TaskStreamStats
  working_memory?: WorkingMemoryStats
  memory_index?: MemoryIndexStats
  health_monitor?: HealthMonitorStatus
  election?: ElectionStatus
}

// ── Cluster Metrics ──
export interface ClusterMetrics {
  cluster_enabled: boolean
  agent_id?: string
  uptime_seconds?: number
  timestamp?: number
  agents?: {
    total: number
    primary: number
    secondary: number
    standby: number
    healthy: number
    unhealthy: number
    total_load: number
    total_capacity: number
    load_ratio: number
  }
  tasks?: {
    published_total: number
    consumed_total: number
    completed_total: number
    failed_total: number
    dead_lettered_total: number
    queue_depth: number
    queue_high: number
    queue_normal: number
    queue_low: number
  }
  working_memory?: {
    reads_total: number
    writes_total: number
    promotions_total: number
    evictions_total: number
    active_sessions: number
    promotion_queue_size: number
  }
  memory_index?: {
    stored_total: number
    searched_total: number
    duplicates_found_total: number
    index_available: number
    total_memories: number
  }
  health?: {
    checks_total: number
    sdown_events_total: number
    odown_events_total: number
    sdown_agents: number
    odown_agents: number
  }
  election?: {
    in_progress: number
    elections_won_total: number
    elections_lost_total: number
    demotions_total: number
    min_secondaries_met: number
  }
  event_bus?: {
    published_total: number
    received_total: number
    errors_total: number
    handler_count: number
  }
  redis?: {
    connected: number
    used_memory_bytes: number
    used_memory_peak_bytes: number
    used_memory_rss_bytes: number
    connected_clients: number
  }
  rates?: Record<string, number>
  rate_limiter?: {
    checks: number
    allowed: number
    denied: number
  }
}

// ── Memory & Knowledge Systems ──
export interface MemorySystemStatus {
  passive_memory: boolean
  embedding_service: {
    model: string
    dims: number
    available: boolean | null
    total_calls: number
    total_errors: number
    cache: {
      size: number
      max_size: number
      hits: number
      misses: number
      hit_rate: number
    }
  } | null
  rag_pipeline: {
    active: boolean
    total_retrievals: number
    total_ingests: number
    avg_retrieve_ms: number
    avg_ingest_ms: number
    embedding: Record<string, unknown> | null
  } | null
  knowledge_graph: {
    total_entities: number
    total_relationships: number
    entity_types: Record<string, number>
    relationship_types: Record<string, number>
    total_extractions: number
    avg_extract_ms: number
  } | null
  working_memory: boolean
  memory_index: boolean
}

export interface KnowledgeGraphData {
  nodes: Array<{
    id: string
    name: string
    type: string
    properties: Record<string, unknown>
    mention_count: number
    first_seen: number
    last_seen: number
  }>
  links: Array<{
    source: string
    target: string
    type: string
    strength: number
    mention_count: number
  }>
  stats: Record<string, unknown>
}

// ── Setup ──
export interface SetupStatusResponse {
  setup_complete: boolean
  has_admin_key: boolean
  has_model: boolean
  has_telegram: boolean
}

export interface SetupCompleteResponse {
  success: boolean
  message: string
}
