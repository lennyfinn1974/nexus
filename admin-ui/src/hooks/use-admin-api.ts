import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api-client'
import type {
  StatusResponse, HealthResponse, UsageResponse, Conversation,
  PluginsResponse, ModelsResponse, OllamaListResponse, SettingsResponse,
  SettingsUpdateResponse, SystemInfo, Backup, BackupResponse,
  AuditEntry, LogEntry, Task, SystemPromptResponse, Skill, SkillPack,
  TestConnectionResponse,
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
