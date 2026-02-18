import { useMetrics, useMemoryHealth } from '@/hooks/use-admin-api'
import StatCard from '@/components/shared/stat-card'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

function formatMs(ms: number): string {
  if (ms < 1) return '<1ms'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 24) return `${(h / 24).toFixed(1)}d`
  return `${h}h ${m}m`
}

function LatencyRow({ label, data }: { label: string; data: { p50: number; p95: number; p99: number; avg: number; count: number } }) {
  return (
    <tr className="border-b border-border last:border-0">
      <td className="py-2 pr-4 text-sm font-medium">{label}</td>
      <td className="py-2 pr-4 font-mono text-sm text-muted-foreground">{formatMs(data.p50)}</td>
      <td className="py-2 pr-4 font-mono text-sm text-muted-foreground">{formatMs(data.p95)}</td>
      <td className="py-2 pr-4 font-mono text-sm text-muted-foreground">{formatMs(data.p99)}</td>
      <td className="py-2 pr-4 font-mono text-sm text-muted-foreground">{formatMs(data.avg)}</td>
      <td className="py-2 font-mono text-sm text-muted-foreground">{data.count.toLocaleString()}</td>
    </tr>
  )
}

export default function MetricsPage() {
  const { data: metrics, isLoading } = useMetrics(30000)
  const { data: memHealth } = useMemoryHealth(60000)

  if (isLoading) return <CardSkeleton />

  const counters = metrics?.counters ?? {}
  const latency = metrics?.latency ?? {}

  return (
    <div className="space-y-6">
      {/* Top-level counters */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
        <StatCard label="Uptime" value={formatUptime(metrics?.uptime_seconds ?? 0)} sub="since last start" />
        <StatCard label="Turns" value={(counters.total_turns ?? 0).toLocaleString()} sub="conversations" />
        <StatCard label="Tool Calls" value={(counters.total_tool_calls ?? 0).toLocaleString()} sub={`${counters.tool_errors ?? 0} errors`} />
        <StatCard label="Ollama" value={(counters.ollama_calls ?? 0).toLocaleString()} sub="local calls" />
        <StatCard label="Claude" value={(counters.claude_calls ?? 0).toLocaleString()} sub="API calls" />
        <StatCard label="Failovers" value={counters.failovers ?? 0} sub={`${counters.aborts ?? 0} aborts`} />
      </div>

      {/* Tool safety counters */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="Idempotency Hits" value={counters.idempotency_hits ?? 0} sub="cached results reused" />
        <StatCard label="Tool Timeouts" value={counters.tool_timeouts ?? 0} sub="execution timeouts" />
        <StatCard label="Memories" value={`${counters.memories_pruned ?? 0} pruned`} sub={`${counters.memories_archived ?? 0} archived`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Latency percentiles */}
        <Card className="border-border bg-card">
          <CardHeader><CardTitle className="text-sm">Latency Percentiles (last 24h)</CardTitle></CardHeader>
          <CardContent>
            {Object.keys(latency).length === 0 ? (
              <p className="text-sm text-muted-foreground">No latency data yet. Make some requests first.</p>
            ) : (
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    <th className="pb-2 text-left">Metric</th>
                    <th className="pb-2 text-left">p50</th>
                    <th className="pb-2 text-left">p95</th>
                    <th className="pb-2 text-left">p99</th>
                    <th className="pb-2 text-left">avg</th>
                    <th className="pb-2 text-left">count</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(latency).map(([key, data]) => (
                    <LatencyRow key={key} label={key.replace(/_/g, ' ')} data={data as any} />
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>

        {/* Memory health */}
        <Card className="border-border bg-card">
          <CardHeader><CardTitle className="text-sm">Memory Health</CardTitle></CardHeader>
          <CardContent>
            {!memHealth || memHealth.status === 'no_memory_index' ? (
              <p className="text-sm text-muted-foreground">Memory index not active.</p>
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <div className="text-[10px] font-semibold uppercase text-muted-foreground">Active</div>
                    <div className="font-mono text-xl font-bold">{memHealth.total_active ?? 0}</div>
                  </div>
                  <div>
                    <div className="text-[10px] font-semibold uppercase text-muted-foreground">Archived</div>
                    <div className="font-mono text-xl font-bold">{memHealth.archived?.archived_count ?? 0}</div>
                  </div>
                  <div>
                    <div className="text-[10px] font-semibold uppercase text-muted-foreground">Dedup Blocked</div>
                    <div className="font-mono text-xl font-bold">{memHealth.duplicates_blocked ?? 0}</div>
                  </div>
                </div>

                {/* Age distribution */}
                {memHealth.age_distribution && (
                  <div>
                    <div className="mb-2 text-[10px] font-semibold uppercase text-muted-foreground">Age Distribution</div>
                    <div className="flex gap-2">
                      {Object.entries(memHealth.age_distribution as Record<string, number>).map(([bucket, count]) => (
                        <div key={bucket} className="flex-1 rounded bg-secondary p-2 text-center">
                          <div className="font-mono text-sm font-bold">{count}</div>
                          <div className="text-[10px] text-muted-foreground">{bucket}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Importance stats */}
                {memHealth.avg_importance !== undefined && (
                  <div className="flex gap-4 text-sm">
                    <span className="text-muted-foreground">Avg importance: <span className="font-mono text-foreground">{memHealth.avg_importance}</span></span>
                    <span className="text-muted-foreground">Dedup threshold: <span className="font-mono text-foreground">{memHealth.dedup_threshold}</span></span>
                  </div>
                )}

                {/* Types */}
                {memHealth.by_type && Object.keys(memHealth.by_type).length > 0 && (
                  <div>
                    <div className="mb-2 text-[10px] font-semibold uppercase text-muted-foreground">By Type</div>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(memHealth.by_type as Record<string, number>).map(([type, count]) => (
                        <span key={type} className="rounded-full bg-secondary px-3 py-1 text-xs">
                          {type}: <span className="font-mono font-bold">{count}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Plugin audit + RAG stats */}
      <div className="grid gap-6 lg:grid-cols-2">
        {metrics?.plugin_audit && Object.keys(metrics.plugin_audit).length > 0 && (
          <Card className="border-border bg-card">
            <CardHeader><CardTitle className="text-sm">Plugin Tool Usage</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-2">
                {Object.entries(metrics.plugin_audit as Record<string, Record<string, number>>).map(([plugin, tools]) => (
                  <div key={plugin}>
                    <div className="text-xs font-semibold text-muted-foreground">{plugin}</div>
                    <div className="ml-2 flex flex-wrap gap-2">
                      {Object.entries(tools).map(([tool, count]) => (
                        <span key={tool} className="rounded bg-secondary px-2 py-0.5 font-mono text-[11px]">
                          {tool}: {count}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {metrics?.rag && (
          <Card className="border-border bg-card">
            <CardHeader><CardTitle className="text-sm">RAG Pipeline</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-1 text-sm">
                {Object.entries(metrics.rag as Record<string, any>).map(([key, val]) => (
                  <div key={key} className="flex justify-between">
                    <span className="text-muted-foreground">{key.replace(/_/g, ' ')}</span>
                    <span className="font-mono">{typeof val === 'number' ? val.toLocaleString() : String(val)}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
