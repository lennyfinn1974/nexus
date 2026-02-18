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
  BrandProfile, MarketingCampaign, CampaignSummary, ContentItem,
  CalendarEvent, MarketingAnalytics, PlatformConnection,
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

export const useMetrics = (refetchInterval = 30000) =>
  useQuery({
    queryKey: ['admin', 'metrics'],
    queryFn: () => api.get<Record<string, any>>('/admin/metrics'),
    refetchInterval,
  })

export const useMemoryHealth = (refetchInterval = 60000) =>
  useQuery({
    queryKey: ['admin', 'memory-health'],
    queryFn: () => api.get<Record<string, any>>('/admin/memory/health'),
    refetchInterval,
  })

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

// ── Marketing ──

export const useBrandProfiles = () =>
  useQuery({
    queryKey: ['marketing', 'brand-profiles'],
    queryFn: () => api.get<{ profiles: BrandProfile[]; total: number }>('/marketing/brand-profiles'),
  })

export const useCampaigns = (status?: string, campaignType?: string) =>
  useQuery({
    queryKey: ['marketing', 'campaigns', status, campaignType],
    queryFn: () => {
      const params = new URLSearchParams()
      if (status) params.set('status', status)
      if (campaignType) params.set('campaign_type', campaignType)
      const qs = params.toString()
      return api.get<{ campaigns: MarketingCampaign[]; total: number }>(
        `/marketing/campaigns${qs ? `?${qs}` : ''}`
      )
    },
  })

export const useCampaignDetail = (campaignId: string | null) =>
  useQuery({
    queryKey: ['marketing', 'campaigns', campaignId],
    queryFn: () => api.get<{ campaign: CampaignSummary }>(`/marketing/campaigns/${campaignId}`),
    enabled: !!campaignId,
  })

export const useMarketingContent = (campaignId?: string, status?: string, platform?: string) =>
  useQuery({
    queryKey: ['marketing', 'content', campaignId, status, platform],
    queryFn: () => {
      const params = new URLSearchParams()
      if (campaignId) params.set('campaign_id', campaignId)
      if (status) params.set('status', status)
      if (platform) params.set('platform', platform)
      const qs = params.toString()
      return api.get<{ items: ContentItem[]; total: number }>(
        `/marketing/content${qs ? `?${qs}` : ''}`
      )
    },
  })

export const useApprovalQueue = () =>
  useQuery({
    queryKey: ['marketing', 'approval-queue'],
    queryFn: () => api.get<{ items: ContentItem[]; total: number }>('/marketing/approval-queue'),
  })

export const useMarketingCalendar = (start?: string, end?: string) =>
  useQuery({
    queryKey: ['marketing', 'calendar', start, end],
    queryFn: () => {
      const params = new URLSearchParams()
      if (start) params.set('start', start)
      if (end) params.set('end', end)
      const qs = params.toString()
      return api.get<{ events: CalendarEvent[] }>(
        `/marketing/calendar${qs ? `?${qs}` : ''}`
      )
    },
  })

export const useMarketingAnalytics = (source?: string, days = 30) =>
  useQuery({
    queryKey: ['marketing', 'analytics', source, days],
    queryFn: () => {
      const params = new URLSearchParams()
      if (source) params.set('source', source)
      params.set('days', String(days))
      return api.get<MarketingAnalytics>(`/marketing/analytics?${params.toString()}`)
    },
  })

export const useMarketingPlatforms = () =>
  useQuery({
    queryKey: ['marketing', 'platforms'],
    queryFn: () => api.get<{ platforms: PlatformConnection[] }>('/marketing/platforms'),
  })

// ── Marketing Mutations ──

export function useCreateCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.post<{ status: string; campaign: MarketingCampaign }>('/marketing/campaigns', data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['marketing', 'campaigns'] }),
  })
}

export function useUpdateCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Record<string, unknown> }) =>
      api.put<{ status: string; campaign: MarketingCampaign }>(`/marketing/campaigns/${id}`, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['marketing', 'campaigns'] }),
  })
}

export function useCreateContent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.post<{ status: string; item: ContentItem }>('/marketing/content', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['marketing', 'content'] })
      qc.invalidateQueries({ queryKey: ['marketing', 'approval-queue'] })
    },
  })
}

export function useUpdateContent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Record<string, unknown> }) =>
      api.put<{ status: string; item: ContentItem }>(`/marketing/content/${id}`, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['marketing', 'content'] }),
  })
}

export function useApproveContent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (contentId: string) =>
      api.post<{ status: string; item: ContentItem }>(`/marketing/content/${contentId}/approve`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['marketing', 'content'] })
      qc.invalidateQueries({ queryKey: ['marketing', 'approval-queue'] })
    },
  })
}

export function useRejectContent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (contentId: string) =>
      api.post<{ status: string; item: ContentItem }>(`/marketing/content/${contentId}/reject`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['marketing', 'content'] })
      qc.invalidateQueries({ queryKey: ['marketing', 'approval-queue'] })
    },
  })
}

export function usePublishContent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (contentId: string) =>
      api.post<{ status: string; item: ContentItem }>(`/marketing/content/${contentId}/publish`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['marketing', 'content'] }),
  })
}

export function useScheduleContent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ contentId, scheduledAt }: { contentId: string; scheduledAt: string }) =>
      api.post<{ status: string; item: ContentItem }>(`/marketing/content/${contentId}/schedule`, {
        scheduled_at: scheduledAt,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['marketing', 'content'] })
      qc.invalidateQueries({ queryKey: ['marketing', 'calendar'] })
    },
  })
}

export function useCreateBrandProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.post<{ status: string; profile: BrandProfile }>('/marketing/brand-profiles', data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['marketing', 'brand-profiles'] }),
  })
}

export function useUpdateBrandProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Record<string, unknown> }) =>
      api.put<{ status: string; profile: BrandProfile }>(`/marketing/brand-profiles/${id}`, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['marketing', 'brand-profiles'] }),
  })
}

export function useDeleteBrandProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api.delete<{ status: string; id: number }>(`/marketing/brand-profiles/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['marketing', 'brand-profiles'] }),
  })
}
