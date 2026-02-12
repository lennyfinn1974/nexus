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
