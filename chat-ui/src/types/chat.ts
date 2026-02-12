export interface Message {
  id?: number
  conversation_id?: string
  role: 'user' | 'assistant' | 'system'
  content: string
  model_used?: string | null
  tokens_in?: number
  tokens_out?: number
  created_at?: string
}

export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface SearchResult {
  id: number
  conversation_id: string
  role: string
  content: string
  model_used: string | null
  created_at: string | null
  conversation_title: string
  rank: number
  headline: string
}

export interface StatusData {
  models: {
    claude_available: boolean
    ollama_available: boolean
    claude_code_available?: boolean
  }
  tasks_active: number
  skills_count: number
  plugins: Record<string, unknown>
}

export type WSMessageType =
  | 'stream_start'
  | 'stream_chunk'
  | 'stream_end'
  | 'message'
  | 'system'
  | 'error'
  | 'conversation_set'
  | 'conversation_renamed'
  | 'ping'
  | 'sub_agent_start'
  | 'sub_agent_progress'
  | 'sub_agent_complete'
  | 'work_item_update'

export interface WSMessage {
  type: WSMessageType
  content?: string
  model?: string
  conv_id?: string
  title?: string
  // Sub-agent fields
  orchestration_id?: string
  strategy?: string
  sub_agent_count?: number
  sub_agents?: SubAgentInfo[]
  sub_agent_id?: string
  sub_agent_role?: string
  sub_agent_model?: string
  sub_agent_status?: string
  duration_ms?: number
  // Work item fields
  event?: 'registered' | 'updated'
  item?: {
    id: string
    kind: string
    status: string
    title: string
  }
}

// ── Sub-Agent Types ──

export interface SubAgentInfo {
  id: string
  role: string
  model: string
}

export interface SubAgentState {
  id: string
  role: string
  model: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  content: string
  duration_ms?: number
}

export interface OrchestrationState {
  id: string
  strategy: string
  agents: SubAgentState[]
  active: boolean
}
