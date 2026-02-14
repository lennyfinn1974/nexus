import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api-client'
import type {
  StatusResponse, HealthResponse, UsageResponse, Conversation,
  PluginsResponse, ModelsResponse, OllamaListResponse, SettingsResponse,
  SettingsUpdateResponse, SystemInfo, Backup, BackupResponse,
  AuditEntry, LogEntry, Task, SystemPromptResponse, Skill, SkillPack,
  TestConnectionResponse, CatalogSearchResponse, CatalogCategory,
  CatalogInstallResponse, SetupStatusResponse, SetupCompleteResponse,
  WorkItem, WorkItemCounts,
  ClusterStatusResponse, ClusterAgent, ClusterMetrics,
  MemorySystemStatus, KnowledgeGraphData,
} from '@/types/api'

// ── Queries ──

export const useStatus = () =>
  useQuery({ queryKey: ['status'], queryFn: () => api.get<StatusResponse>('/status') })

export const useHealth = (refetchInterval?: number) =>
  useQuery({
    queryKey: ['health'],
    queryFn: () => api.get<HealthResponse>('/health'),
    refetchInterval,
  })

export const useUsage = () =>
  useQuery({ queryKey: ['admin', 'usage'], queryFn: () => api.get<UsageResponse>('/admin/usage') })

export const useConversations = () =>
  useQuery({ queryKey: ['admin', 'conversations'], queryFn: () => api.get<Conversation[]>('/admin/conversations') })

export const usePlugins = () =>
  useQuery({ queryKey: ['admin', 'plugins'], queryFn: () => api.get<PluginsResponse>('/admin/plugins') })

export const useModels = () =>
  useQuery({ queryKey: ['admin', 'models'], queryFn: () => api.get<ModelsResponse>('/admin/models') })

export const useOllamaModels = () =>
  useQuery({
    queryKey: ['admin', 'ollama-models'],
    queryFn: () => api.get<OllamaListResponse>('/admin/models/ollama-list'),
    enabled: false, // manual only
  })

export const useSettings = () =>
  useQuery({ queryKey: ['admin', 'settings'], queryFn: () => api.get<SettingsResponse>('/admin/settings') })

export const useSystemInfo = () =>
  useQuery({ queryKey: ['admin', 'system'], queryFn: () => api.get<SystemInfo>('/admin/system') })

export const useBackups = () =>
  useQuery({ queryKey: ['admin', 'backups'], queryFn: () => api.get<Backup[]>('/admin/backups') })

export const useAuditLog = () =>
  useQuery({ queryKey: ['admin', 'audit'], queryFn: () => api.get<AuditEntry[]>('/admin/audit') })

export const useLogs = () =>
  useQuery({ queryKey: ['admin', 'logs'], queryFn: () => api.get<LogEntry[]>('/admin/logs'), staleTime: 5000 })

export const useTasks = (refetchInterval?: number) =>
  useQuery({
    queryKey: ['tasks'],
    queryFn: () => api.get<Task[]>('/tasks'),
    refetchInterval,
  })

export const useWorkstreams = () =>
  useQuery({
    queryKey: ['admin', 'workstreams'],
    queryFn: () => api.get<WorkItem[]>('/admin/workstreams'),
  })

export const useWorkstreamCounts = (refetchInterval?: number) =>
  useQuery({
    queryKey: ['admin', 'workstreams', 'counts'],
    queryFn: () => api.get<WorkItemCounts>('/admin/workstreams/counts'),
    refetchInterval,
  })

export const useSystemPrompt = () =>
  useQuery({ queryKey: ['admin', 'system-prompt'], queryFn: () => api.get<SystemPromptResponse>('/admin/system-prompt') })

export const useSkills = () =>
  useQuery({ queryKey: ['admin', 'skills'], queryFn: () => api.get<Skill[]>('/admin/skills') })

export const useSkillPacks = () =>
  useQuery({ queryKey: ['admin', 'skill-packs'], queryFn: () => api.get<SkillPack[]>('/admin/skills/packs') })

// ── Mutations ──

export function useUpdateSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (updates: Record<string, string>) =>
      api.post<SettingsUpdateResponse>('/admin/settings', { updates }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'settings'] })
      qc.invalidateQueries({ queryKey: ['admin', 'models'] })
    },
  })
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (key: string) => api.post<TestConnectionResponse>(`/admin/settings/test/${key}`),
  })
}

export function useDeleteConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<{ deleted: string }>(`/admin/conversations/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'conversations'] }),
  })
}

export function useDeleteAllConversations() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.delete<{ deleted: number }>('/admin/conversations'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'conversations'] }),
  })
}

export function useReloadPlugin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.post<{ success: boolean; message?: string; error?: string }>(`/admin/plugins/${name}/reload`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'plugins'] }),
  })
}

export function useReloadAllPlugins() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<{ success: boolean; message?: string; error?: string }>('/admin/plugins/reload-all'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'plugins'] }),
  })
}

export function useCreateBackup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<BackupResponse>('/admin/backup'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'backups'] }),
  })
}

export function useRestartServer() {
  return useMutation({
    mutationFn: () => api.post<{ success: boolean; message: string }>('/admin/restart'),
  })
}

export function useInstallSkillPack() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (packId: string) => api.post<{ success: boolean; skill: unknown }>(`/admin/skills/install/${packId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'skills'] })
      qc.invalidateQueries({ queryKey: ['admin', 'skill-packs'] })
    },
  })
}

export function useDeleteSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<{ deleted: string }>(`/admin/skills/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'skills'] }),
  })
}

// ── Setup ──

export const useSetupStatus = () =>
  useQuery({
    queryKey: ['setup', 'status'],
    queryFn: () => api.get<SetupStatusResponse>('/setup/status'),
    staleTime: 10000,
  })

export function useCompleteSetup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (adminKey: string) =>
      api.post<SetupCompleteResponse>('/admin/setup/complete', { admin_key: adminKey }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['setup', 'status'] })
      qc.invalidateQueries({ queryKey: ['admin', 'settings'] })
    },
  })
}

// ── Catalog ──

export const useCatalogSearch = (query: string, category: string) =>
  useQuery({
    queryKey: ['admin', 'catalog', 'search', query, category],
    queryFn: () => api.get<CatalogSearchResponse>(
      `/admin/catalog/search?q=${encodeURIComponent(query)}&category=${encodeURIComponent(category)}&limit=20`
    ),
    enabled: query.length > 0 || category.length > 0,
    staleTime: 30000,
  })

export const useCatalogCategories = () =>
  useQuery({
    queryKey: ['admin', 'catalog', 'categories'],
    queryFn: () => api.get<CatalogCategory[]>('/admin/catalog/categories'),
  })

export function useInstallCatalogSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (skillId: string) =>
      api.post<CatalogInstallResponse>(`/admin/catalog/${skillId}/install`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'skills'] })
      qc.invalidateQueries({ queryKey: ['admin', 'catalog'] })
    },
  })
}

// ── Cluster ──

export const useClusterStatus = (refetchInterval?: number) =>
  useQuery({
    queryKey: ['admin', 'cluster', 'status'],
    queryFn: () => api.get<ClusterStatusResponse>('/admin/cluster/status'),
    refetchInterval,
  })

export const useClusterAgents = (refetchInterval?: number) =>
  useQuery({
    queryKey: ['admin', 'cluster', 'agents'],
    queryFn: () => api.get<ClusterAgent[]>('/admin/cluster/agents'),
    refetchInterval,
  })

export const useClusterMetrics = (refetchInterval?: number) =>
  useQuery({
    queryKey: ['admin', 'cluster', 'metrics'],
    queryFn: () => api.get<ClusterMetrics>('/admin/cluster/metrics'),
    refetchInterval,
    enabled: true,
  })

// ── Memory & Knowledge ──

export const useMemoryStatus = (refetchInterval?: number) =>
  useQuery({
    queryKey: ['admin', 'memory', 'status'],
    queryFn: () => api.get<MemorySystemStatus>('/admin/memory/status'),
    refetchInterval,
  })

export const useKnowledgeGraph = (maxEntities = 100) =>
  useQuery({
    queryKey: ['admin', 'memory', 'knowledge-graph', maxEntities],
    queryFn: () => api.get<KnowledgeGraphData>(`/admin/memory/knowledge-graph?max_entities=${maxEntities}`),
  })
