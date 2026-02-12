import { useState, useEffect, useRef, useCallback } from 'react'
import { useWorkstreams } from '@/hooks/use-admin-api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import StatCard from '@/components/shared/stat-card'
import StatusBadge from '@/components/shared/status-badge'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import type { WorkItem } from '@/types/api'
import {
  Bot, GitBranch, ClipboardList, ListChecks, Cog, Bell, Network,
} from 'lucide-react'

const KIND_CONFIG: Record<string, { label: string; icon: typeof Bot; color: string }> = {
  agent:         { label: 'Agent',        icon: Bot,           color: 'bg-blue-500/15 text-blue-500' },
  sub_agent:     { label: 'Sub-Agent',    icon: GitBranch,     color: 'bg-purple-500/15 text-purple-500' },
  orchestration: { label: 'Orchestration',icon: Network,       color: 'bg-indigo-500/15 text-indigo-500' },
  plan:          { label: 'Plan',         icon: ClipboardList, color: 'bg-amber-500/15 text-amber-500' },
  plan_step:     { label: 'Step',         icon: ListChecks,    color: 'bg-amber-400/15 text-amber-400' },
  task:          { label: 'Task',         icon: Cog,           color: 'bg-emerald-500/15 text-emerald-500' },
  reminder:      { label: 'Reminder',     icon: Bell,          color: 'bg-pink-500/15 text-pink-500' },
}

const COLUMNS: { key: string; label: string; color: string }[] = [
  { key: 'pending',   label: 'Pending',   color: 'text-warning' },
  { key: 'running',   label: 'Running',   color: 'text-primary' },
  { key: 'completed', label: 'Completed', color: 'text-success' },
  { key: 'failed',    label: 'Failed',    color: 'text-destructive' },
]

function formatDuration(item: WorkItem): string {
  if (!item.started_at) return ''
  const end = item.completed_at ? new Date(item.completed_at) : new Date()
  const start = new Date(item.started_at)
  const ms = end.getTime() - start.getTime()
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

function WorkItemCard({ item, children: childItems }: { item: WorkItem; children: WorkItem[] }) {
  const [expanded, setExpanded] = useState(false)
  const cfg = KIND_CONFIG[item.kind] || KIND_CONFIG.task
  const Icon = cfg.icon
  const hasChildren = childItems.length > 0

  return (
    <div className="rounded-lg border border-border bg-card/50 p-2.5 space-y-1.5">
      <div
        className="flex items-start gap-2 cursor-pointer"
        onClick={() => hasChildren && setExpanded(!expanded)}
      >
        <div className={`mt-0.5 rounded p-1 ${cfg.color}`}>
          <Icon className="h-3 w-3" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium truncate">{item.title || item.id}</p>
          <div className="flex items-center gap-1.5 mt-0.5">
            <Badge variant="outline" className={`text-[9px] px-1 py-0 h-4 ${cfg.color}`}>
              {cfg.label}
            </Badge>
            {item.model && (
              <span className="font-mono text-[9px] text-muted-foreground">{item.model}</span>
            )}
            {item.started_at && (
              <span className="text-[9px] text-muted-foreground ml-auto">
                {formatDuration(item)}
              </span>
            )}
          </div>
        </div>
        {hasChildren && (
          <span className="text-[10px] text-muted-foreground mt-1">
            {expanded ? '▾' : '▸'} {childItems.length}
          </span>
        )}
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[9px] text-muted-foreground">{formatTime(item.created_at)}</span>
        <StatusBadge status={item.status} />
      </div>
      {expanded && childItems.length > 0 && (
        <div className="ml-3 pt-1 space-y-1.5 border-l border-border pl-2">
          {childItems.map((child) => (
            <WorkItemCard key={child.id} item={child} children={[]} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function WorkStreamsPage() {
  const { data: initialItems, isLoading } = useWorkstreams()
  const [items, setItems] = useState<WorkItem[]>([])
  const [kindFilter, setKindFilter] = useState('all')
  const [sseStatus, setSseStatus] = useState('Connecting...')
  const controllerRef = useRef<AbortController | null>(null)

  // Load initial data
  useEffect(() => {
    if (initialItems) setItems(initialItems)
  }, [initialItems])

  // SSE stream for real-time updates
  const startStream = useCallback(() => {
    const token = sessionStorage.getItem('admin_api_key')
    if (!token) return

    const controller = new AbortController()
    controllerRef.current = controller

    fetch('/api/admin/workstreams/stream', {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then((res) => {
        if (!res.ok || !res.body) {
          setSseStatus('Failed')
          return
        }
        setSseStatus('Live')
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        function read(): Promise<void> {
          return reader.read().then(({ done, value }) => {
            if (done) { setSseStatus('Disconnected'); return }
            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() ?? ''
            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const event = JSON.parse(line.slice(6))
                  if (event.type === 'snapshot') {
                    setItems(event.items ?? [])
                  } else if (event.type === 'work_item_update' && event.item) {
                    setItems((prev) => {
                      const idx = prev.findIndex((i) => i.id === event.item.id)
                      if (idx >= 0) {
                        const next = [...prev]
                        next[idx] = { ...next[idx], ...event.item }
                        return next
                      }
                      return [event.item, ...prev]
                    })
                  }
                } catch { /* skip malformed */ }
              }
            }
            return read()
          })
        }
        read()
      })
      .catch((err) => {
        if (err.name !== 'AbortError') {
          setSseStatus('Reconnecting...')
          setTimeout(startStream, 3000)
        }
      })
  }, [])

  useEffect(() => {
    startStream()
    return () => controllerRef.current?.abort()
  }, [startStream])

  if (isLoading) return <CardSkeleton />

  // Filter items
  const filtered = kindFilter === 'all'
    ? items
    : items.filter((i) => i.kind === kindFilter)

  // Group by status for KanBan columns
  const byStatus: Record<string, WorkItem[]> = {
    pending: [], running: [], completed: [], failed: [],
  }
  // Separate parent and child items
  const childMap: Record<string, WorkItem[]> = {}
  for (const item of filtered) {
    if (item.parent_id) {
      if (!childMap[item.parent_id]) childMap[item.parent_id] = []
      childMap[item.parent_id].push(item)
    } else {
      const col = byStatus[item.status]
      if (col) col.push(item)
      else byStatus.pending.push(item)
    }
  }

  // Counts
  const counts = { pending: 0, running: 0, completed: 0, failed: 0 }
  for (const item of filtered) {
    const s = item.status as keyof typeof counts
    if (s in counts) counts[s]++
  }

  const kinds = ['all', 'agent', 'sub_agent', 'orchestration', 'plan', 'plan_step', 'task', 'reminder']

  return (
    <div className="space-y-6">
      {/* Status row */}
      <div className="flex items-center justify-between">
        <div className="grid gap-3 sm:grid-cols-4 flex-1">
          <StatCard label="Pending" value={<span className="text-warning">{counts.pending}</span>} sub="queued" />
          <StatCard label="Running" value={<span className="text-primary">{counts.running}</span>} sub="active" />
          <StatCard label="Completed" value={<span className="text-success">{counts.completed}</span>} sub="done" />
          <StatCard label="Failed" value={<span className="text-destructive">{counts.failed}</span>} sub="errors" />
        </div>
        <div className="ml-4 flex items-center gap-1.5">
          <span
            className="h-2 w-2 rounded-full"
            style={{
              background: sseStatus === 'Live' ? 'var(--success, #22c55e)' : 'var(--warning, #f59e0b)',
              boxShadow: sseStatus === 'Live' ? '0 0 6px var(--success, #22c55e)' : 'none',
            }}
          />
          <span className="text-[10px] text-muted-foreground">{sseStatus}</span>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex gap-1 flex-wrap">
        {kinds.map((k) => (
          <Button
            key={k}
            variant={kindFilter === k ? 'default' : 'outline'}
            size="sm"
            className="h-7 text-xs capitalize"
            onClick={() => setKindFilter(k)}
          >
            {k === 'all' ? 'All' : (KIND_CONFIG[k]?.label ?? k)}
            {k !== 'all' && (
              <span className="ml-1 text-muted-foreground">
                ({filtered.filter((i) => k === 'all' || i.kind === k).length})
              </span>
            )}
          </Button>
        ))}
      </div>

      {/* KanBan columns */}
      <div className="grid grid-cols-4 gap-4" style={{ minHeight: 400 }}>
        {COLUMNS.map((col) => (
          <Card key={col.key} className="border-border bg-card flex flex-col">
            <CardHeader className="py-2 px-3">
              <CardTitle className={`text-xs font-semibold ${col.color}`}>
                {col.label}
                <span className="ml-1.5 text-muted-foreground font-normal">
                  ({byStatus[col.key]?.length ?? 0})
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="flex-1 p-2 pt-0">
              <ScrollArea className="h-[calc(100vh-340px)]">
                <div className="space-y-2 pr-2">
                  {(byStatus[col.key] ?? []).length === 0 ? (
                    <p className="text-[10px] text-muted-foreground text-center py-8">
                      No items
                    </p>
                  ) : (
                    (byStatus[col.key] ?? []).map((item) => (
                      <WorkItemCard
                        key={item.id}
                        item={item}
                        children={childMap[item.id] ?? []}
                      />
                    ))
                  )}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
