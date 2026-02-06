import { useState } from 'react'
import { useTasks, useUsage } from '@/hooks/use-admin-api'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import StatCard from '@/components/shared/stat-card'
import StatusBadge from '@/components/shared/status-badge'
import { CardSkeleton } from '@/components/shared/loading-skeleton'

export default function MonitoringPage() {
  return (
    <Tabs defaultValue="tasks" className="space-y-4">
      <TabsList>
        <TabsTrigger value="tasks">Task Queue</TabsTrigger>
        <TabsTrigger value="metrics">Performance Metrics</TabsTrigger>
      </TabsList>

      <TabsContent value="tasks"><TaskQueueTab /></TabsContent>
      <TabsContent value="metrics"><MetricsTab /></TabsContent>
    </Tabs>
  )
}

function TaskQueueTab() {
  const [filter, setFilter] = useState<string>('all')
  const hasRunning = true
  const { data: tasks, isLoading } = useTasks(hasRunning ? 5000 : undefined)

  if (isLoading) return <CardSkeleton />

  const filtered = filter === 'all' ? (tasks ?? []) : (tasks ?? []).filter((t) => t.status === filter)

  const counts: Record<string, number> = {}
  for (const t of tasks ?? []) {
    counts[t.status] = (counts[t.status] ?? 0) + 1
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap">
        {['all', 'pending', 'running', 'completed', 'failed'].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
              filter === f ? 'bg-primary text-primary-foreground' : 'bg-secondary text-secondary-foreground hover:bg-muted'
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
            {f !== 'all' && counts[f] ? ` (${counts[f]})` : f === 'all' ? ` (${tasks?.length ?? 0})` : ''}
          </button>
        ))}
      </div>

      <Card className="border-border bg-card">
        <CardContent className="pt-6">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Result</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.length === 0 ? (
                <TableRow><TableCell colSpan={5} className="text-center text-muted-foreground">No tasks</TableCell></TableRow>
              ) : (
                filtered.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-mono text-xs">{t.id}</TableCell>
                    <TableCell className="text-xs">{t.type}</TableCell>
                    <TableCell><StatusBadge status={t.status} /></TableCell>
                    <TableCell className="font-mono text-[10px] text-muted-foreground">{t.created_at}</TableCell>
                    <TableCell className="max-w-48 truncate text-xs text-muted-foreground">{t.result ?? t.error ?? '—'}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}

function MetricsTab() {
  const { data, isLoading } = useUsage()

  if (isLoading) return <CardSkeleton />

  const totals = data?.totals ?? []
  const daily = data?.daily ?? []

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {totals.map((t) => (
          <StatCard
            key={t.model_used}
            label={t.model_used}
            value={t.message_count.toLocaleString()}
            sub={`${(t.total_tokens_in + t.total_tokens_out).toLocaleString()} tokens`}
          />
        ))}
      </div>

      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-sm">Daily Breakdown</CardTitle></CardHeader>
        <CardContent>
          {daily.length === 0 ? (
            <p className="text-sm text-muted-foreground">No usage data yet.</p>
          ) : (
            <>
              {/* CSS bar chart */}
              <div className="mb-6 flex items-end gap-1" style={{ height: 120 }}>
                {daily.slice(0, 14).reverse().map((d, i) => {
                  const total = d.total_tokens_in + d.total_tokens_out
                  const maxTokens = Math.max(...daily.slice(0, 14).map((x) => x.total_tokens_in + x.total_tokens_out), 1)
                  const pct = (total / maxTokens) * 100
                  return (
                    <div key={i} className="group relative flex-1" title={`${d.day}: ${total.toLocaleString()} tokens`}>
                      <div
                        className="w-full rounded-t bg-primary/60 transition-colors group-hover:bg-primary"
                        style={{ height: `${pct}%`, minHeight: total > 0 ? 4 : 0 }}
                      />
                    </div>
                  )
                })}
              </div>

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Day</TableHead>
                    <TableHead>Model</TableHead>
                    <TableHead className="text-right">Messages</TableHead>
                    <TableHead className="text-right">Tokens In</TableHead>
                    <TableHead className="text-right">Tokens Out</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {daily.slice(0, 30).map((d, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-mono text-xs">{d.day}</TableCell>
                      <TableCell className="text-xs">{d.model_used}</TableCell>
                      <TableCell className="text-right font-mono text-xs">{d.message_count}</TableCell>
                      <TableCell className="text-right font-mono text-xs">{d.total_tokens_in.toLocaleString()}</TableCell>
                      <TableCell className="text-right font-mono text-xs">{d.total_tokens_out.toLocaleString()}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
