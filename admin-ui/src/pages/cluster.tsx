import { useClusterStatus, useClusterMetrics } from '@/hooks/use-admin-api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import StatCard from '@/components/shared/stat-card'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import type { ClusterAgent } from '@/types/api'
import {
  Server, Radio, Shield, Wifi, WifiOff, Activity, Clock, Cpu, Network,
  ArrowRight, Inbox, AlertTriangle, Brain, Database, Search, Upload,
  HardDrive, Eye, Tag, HeartPulse, Crown, ShieldAlert, BarChart3,
  Gauge, Lock,
} from 'lucide-react'

function roleBadge(role: string) {
  switch (role) {
    case 'primary':
      return <Badge className="bg-primary/15 text-primary border-primary/30">Primary</Badge>
    case 'secondary':
      return <Badge className="bg-blue-500/15 text-blue-500 border-blue-500/30">Secondary</Badge>
    case 'standby':
      return <Badge className="bg-amber-500/15 text-amber-500 border-amber-500/30">Standby</Badge>
    default:
      return <Badge variant="outline">{role}</Badge>
  }
}

function healthDot(healthy: boolean | undefined) {
  if (healthy === undefined) return null
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${
        healthy ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]' : 'bg-red-500 shadow-[0_0_6px_rgba(239,68,68,0.5)]'
      }`}
    />
  )
}

function formatUptime(startedAt: number): string {
  if (!startedAt) return '—'
  const seconds = Math.floor(Date.now() / 1000) - startedAt
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`
}

function AgentCard({ agent }: { agent: ClusterAgent }) {
  const loadPct = agent.max_load > 0 ? Math.round((agent.current_load / agent.max_load) * 100) : 0

  return (
    <Card className={`border-border bg-card ${agent.is_self ? 'ring-1 ring-primary/40' : ''}`}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {healthDot(agent.healthy)}
            <CardTitle className="text-sm font-mono">{agent.id}</CardTitle>
            {agent.is_self && (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0">this agent</Badge>
            )}
          </div>
          {roleBadge(agent.role)}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Host + Status */}
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Server className="h-3 w-3" />
            <span>{agent.host}:{agent.port}</span>
          </div>
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Activity className="h-3 w-3" />
            <span className={agent.status === 'active' ? 'text-green-500' : 'text-amber-500'}>
              {agent.status}
            </span>
          </div>
        </div>

        {/* Load bar */}
        <div>
          <div className="flex items-center justify-between text-[10px] text-muted-foreground mb-1">
            <span className="flex items-center gap-1">
              <Cpu className="h-3 w-3" />
              Load
            </span>
            <span>{agent.current_load}/{agent.max_load} ({loadPct}%)</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-secondary">
            <div
              className={`h-full rounded-full transition-all ${
                loadPct > 80 ? 'bg-red-500' : loadPct > 50 ? 'bg-amber-500' : 'bg-primary'
              }`}
              style={{ width: `${Math.min(loadPct, 100)}%` }}
            />
          </div>
        </div>

        {/* Heartbeat + Uptime */}
        <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <Radio className="h-3 w-3" />
            <span>
              {agent.heartbeat_age_seconds !== undefined
                ? `${agent.heartbeat_age_seconds}s ago`
                : '—'}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <Clock className="h-3 w-3" />
            <span>Up {formatUptime(agent.started_at)}</span>
          </div>
        </div>

        {/* Models */}
        {agent.models.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {agent.models.map((m) => (
              <Badge key={m} variant="outline" className="text-[10px] px-1.5 py-0">
                {m}
              </Badge>
            ))}
          </div>
        )}

        {/* Capabilities */}
        {agent.capabilities.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {agent.capabilities.map((c) => (
              <Badge key={c} variant="secondary" className="text-[10px] px-1.5 py-0">
                {c}
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function ClusterPage() {
  const { data: status, isLoading } = useClusterStatus(5000) // poll every 5s
  const { data: metrics } = useClusterMetrics(10000) // poll every 10s

  if (isLoading) return <CardSkeleton />

  // Clustering disabled state
  if (!status?.enabled) {
    return (
      <div className="space-y-6">
        <Card className="border-border bg-card">
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <Network className="h-12 w-12 text-muted-foreground/30 mb-4" />
            <h3 className="text-lg font-semibold">Agent Clustering Disabled</h3>
            <p className="text-sm text-muted-foreground mt-2 max-w-md">
              Enable Redis-based agent clustering to run multiple Nexus instances
              with automatic failover, shared memory, and distributed task execution.
            </p>
            <p className="text-xs text-muted-foreground mt-4">
              Set <code className="bg-secondary px-1.5 py-0.5 rounded text-primary">CLUSTER_ENABLED = true</code> in
              Settings → Clustering to activate.
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  // Clustering enabled but not connected
  if (!status.active) {
    return (
      <div className="space-y-6">
        <Card className="border-border bg-card border-destructive/30">
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <WifiOff className="h-12 w-12 text-destructive/50 mb-4" />
            <h3 className="text-lg font-semibold text-destructive">Redis Disconnected</h3>
            <p className="text-sm text-muted-foreground mt-2 max-w-md">
              Clustering is enabled but the Redis connection failed. Check that Redis is running
              and the connection URL is correct in Settings → Clustering.
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  // Active cluster
  const agents = status.agents || []
  const healthyCount = agents.filter((a) => a.healthy).length
  const totalLoad = agents.reduce((sum, a) => sum + a.current_load, 0)
  const totalCapacity = agents.reduce((sum, a) => sum + a.max_load, 0)

  return (
    <div className="space-y-6">
      {/* Status cards */}
      <div className="grid gap-3 sm:grid-cols-4">
        <StatCard
          label="Agents"
          value={agents.length}
          sub={`${healthyCount} healthy`}
        />
        <StatCard
          label="Role"
          value={status.role || '—'}
          sub={`Agent: ${status.agent_id || '—'}`}
        />
        <StatCard
          label="Cluster Load"
          value={totalCapacity > 0 ? `${Math.round((totalLoad / totalCapacity) * 100)}%` : '0%'}
          sub={`${totalLoad}/${totalCapacity} slots`}
        />
        <StatCard
          label="Redis"
          value={
            <span className="flex items-center gap-2">
              <Wifi className="h-5 w-5 text-green-500" />
              Connected
            </span>
          }
          sub={status.redis_url || '—'}
        />
      </div>

      {/* Event Bus Stats */}
      {status.event_bus && (
        <Card className="border-border bg-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Radio className="h-4 w-4" />
              Event Bus
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-4 gap-4 text-center">
              <div>
                <div className="font-mono text-lg font-bold">{status.event_bus.published}</div>
                <div className="text-[10px] text-muted-foreground uppercase">Published</div>
              </div>
              <div>
                <div className="font-mono text-lg font-bold">{status.event_bus.received}</div>
                <div className="text-[10px] text-muted-foreground uppercase">Received</div>
              </div>
              <div>
                <div className="font-mono text-lg font-bold">{status.event_bus.handler_count}</div>
                <div className="text-[10px] text-muted-foreground uppercase">Handlers</div>
              </div>
              <div>
                <div className={`font-mono text-lg font-bold ${status.event_bus.errors > 0 ? 'text-destructive' : ''}`}>
                  {status.event_bus.errors}
                </div>
                <div className="text-[10px] text-muted-foreground uppercase">Errors</div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Task Streams */}
      {status.task_streams && (
        <Card className="border-border bg-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <ArrowRight className="h-4 w-4" />
              Task Streams
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-4 gap-4">
              {(['high', 'normal', 'low'] as const).map((priority) => {
                const stream = status.task_streams?.[priority]
                return (
                  <div key={priority} className="text-center">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
                      {priority}
                    </div>
                    <div className="flex items-center justify-center gap-3">
                      <div>
                        <div className="font-mono text-lg font-bold">
                          <Inbox className="inline h-3 w-3 mr-1 text-muted-foreground" />
                          {stream?.length ?? 0}
                        </div>
                        <div className="text-[10px] text-muted-foreground">queued</div>
                      </div>
                      <div>
                        <div className={`font-mono text-lg font-bold ${(stream?.pending ?? 0) > 0 ? 'text-amber-500' : ''}`}>
                          {stream?.pending ?? 0}
                        </div>
                        <div className="text-[10px] text-muted-foreground">pending</div>
                      </div>
                    </div>
                  </div>
                )
              })}
              <div className="text-center">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
                  dead letter
                </div>
                <div className={`font-mono text-lg font-bold ${(status.task_streams?.dead_letter?.length ?? 0) > 0 ? 'text-destructive' : ''}`}>
                  <AlertTriangle className="inline h-3 w-3 mr-1" />
                  {status.task_streams?.dead_letter?.length ?? 0}
                </div>
                <div className="text-[10px] text-muted-foreground">failed</div>
              </div>
            </div>

            {/* Task Stats */}
            {status.task_stats && (
              <div className="mt-4 pt-3 border-t border-border grid grid-cols-5 gap-2 text-center">
                <div>
                  <div className="font-mono text-sm font-bold">{status.task_stats.published}</div>
                  <div className="text-[10px] text-muted-foreground">Published</div>
                </div>
                <div>
                  <div className="font-mono text-sm font-bold">{status.task_stats.consumed}</div>
                  <div className="text-[10px] text-muted-foreground">Consumed</div>
                </div>
                <div>
                  <div className="font-mono text-sm font-bold text-green-500">{status.task_stats.completed}</div>
                  <div className="text-[10px] text-muted-foreground">Completed</div>
                </div>
                <div>
                  <div className={`font-mono text-sm font-bold ${status.task_stats.failed > 0 ? 'text-amber-500' : ''}`}>{status.task_stats.failed}</div>
                  <div className="text-[10px] text-muted-foreground">Failed</div>
                </div>
                <div>
                  <div className={`font-mono text-sm font-bold ${status.task_stats.dead_lettered > 0 ? 'text-destructive' : ''}`}>{status.task_stats.dead_lettered}</div>
                  <div className="text-[10px] text-muted-foreground">Dead</div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Working Memory */}
      {status.working_memory && (
        <Card className="border-border bg-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Brain className="h-4 w-4" />
              Working Memory
              <Badge variant="outline" className="ml-auto text-[10px] px-1.5 py-0">
                {status.working_memory.active_sessions} sessions
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-5 gap-4 text-center">
              <div>
                <div className="font-mono text-lg font-bold">{status.working_memory.reads}</div>
                <div className="text-[10px] text-muted-foreground uppercase flex items-center justify-center gap-1">
                  <Eye className="h-2.5 w-2.5" />
                  Reads
                </div>
              </div>
              <div>
                <div className="font-mono text-lg font-bold">{status.working_memory.writes}</div>
                <div className="text-[10px] text-muted-foreground uppercase flex items-center justify-center gap-1">
                  <HardDrive className="h-2.5 w-2.5" />
                  Writes
                </div>
              </div>
              <div>
                <div className="font-mono text-lg font-bold text-green-500">{status.working_memory.promotions}</div>
                <div className="text-[10px] text-muted-foreground uppercase flex items-center justify-center gap-1">
                  <Upload className="h-2.5 w-2.5" />
                  Promoted
                </div>
              </div>
              <div>
                <div className="font-mono text-lg font-bold">{status.working_memory.evictions}</div>
                <div className="text-[10px] text-muted-foreground uppercase">Evicted</div>
              </div>
              <div>
                <div className={`font-mono text-lg font-bold ${status.working_memory.promotion_queue_size > 0 ? 'text-amber-500' : ''}`}>
                  {status.working_memory.promotion_queue_size}
                </div>
                <div className="text-[10px] text-muted-foreground uppercase">Queue</div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Memory Index */}
      {status.memory_index && (
        <Card className="border-border bg-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Database className="h-4 w-4" />
              Semantic Memory Index
              <Badge
                variant={status.memory_index.index_available ? 'outline' : 'destructive'}
                className="ml-auto text-[10px] px-1.5 py-0"
              >
                {status.memory_index.index_available ? 'RediSearch Active' : 'Fallback Mode'}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-4 gap-4 text-center">
              <div>
                <div className="font-mono text-lg font-bold">{status.memory_index.total_memories}</div>
                <div className="text-[10px] text-muted-foreground uppercase flex items-center justify-center gap-1">
                  <Brain className="h-2.5 w-2.5" />
                  Memories
                </div>
              </div>
              <div>
                <div className="font-mono text-lg font-bold">{status.memory_index.stored}</div>
                <div className="text-[10px] text-muted-foreground uppercase">Stored</div>
              </div>
              <div>
                <div className="font-mono text-lg font-bold">{status.memory_index.searched}</div>
                <div className="text-[10px] text-muted-foreground uppercase flex items-center justify-center gap-1">
                  <Search className="h-2.5 w-2.5" />
                  Searches
                </div>
              </div>
              <div>
                <div className={`font-mono text-lg font-bold ${status.memory_index.duplicates_found > 0 ? 'text-amber-500' : ''}`}>
                  {status.memory_index.duplicates_found}
                </div>
                <div className="text-[10px] text-muted-foreground uppercase">Deduped</div>
              </div>
            </div>

            {/* Memory Type Breakdown */}
            {status.memory_index.memory_types && Object.keys(status.memory_index.memory_types).length > 0 && (
              <div className="pt-3 border-t border-border">
                <div className="text-[10px] text-muted-foreground uppercase mb-2 flex items-center gap-1">
                  <Tag className="h-2.5 w-2.5" />
                  Memory Types
                </div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(status.memory_index.memory_types).map(([type, count]) => (
                    <Badge key={type} variant="secondary" className="text-[10px] px-2 py-0.5">
                      {type}: {count}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            <div className="text-[10px] text-muted-foreground">
              Vector dimensions: {status.memory_index.vector_dims}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Health Monitor & Election */}
      {(status.health_monitor || status.election) && (
        <Card className="border-border bg-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <HeartPulse className="h-4 w-4" />
              Health &amp; Election
              {status.election?.election_in_progress && (
                <Badge className="ml-auto bg-amber-500/15 text-amber-500 border-amber-500/30 text-[10px] px-1.5 py-0 animate-pulse">
                  Election in Progress
                </Badge>
              )}
              {status.election && !status.election.min_secondaries_met && (
                <Badge className="ml-auto bg-red-500/15 text-red-500 border-red-500/30 text-[10px] px-1.5 py-0">
                  <ShieldAlert className="h-2.5 w-2.5 mr-1" />
                  Low Secondaries
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-6 gap-3 text-center">
              {/* Health Stats */}
              <div>
                <div className="font-mono text-lg font-bold">{status.health_monitor?.checks ?? 0}</div>
                <div className="text-[10px] text-muted-foreground uppercase">Checks</div>
              </div>
              <div>
                <div className={`font-mono text-lg font-bold ${(status.health_monitor?.sdown_events ?? 0) > 0 ? 'text-amber-500' : ''}`}>
                  {status.health_monitor?.sdown_events ?? 0}
                </div>
                <div className="text-[10px] text-muted-foreground uppercase">SDOWN</div>
              </div>
              <div>
                <div className={`font-mono text-lg font-bold ${(status.health_monitor?.odown_events ?? 0) > 0 ? 'text-destructive' : ''}`}>
                  {status.health_monitor?.odown_events ?? 0}
                </div>
                <div className="text-[10px] text-muted-foreground uppercase">ODOWN</div>
              </div>
              {/* Election Stats */}
              <div>
                <div className="font-mono text-lg font-bold flex items-center justify-center gap-1">
                  <Crown className="h-3 w-3 text-amber-500" />
                  {status.election?.elections_won ?? 0}
                </div>
                <div className="text-[10px] text-muted-foreground uppercase">Won</div>
              </div>
              <div>
                <div className="font-mono text-lg font-bold">{status.election?.elections_lost ?? 0}</div>
                <div className="text-[10px] text-muted-foreground uppercase">Lost</div>
              </div>
              <div>
                <div className={`font-mono text-lg font-bold ${(status.election?.demotions ?? 0) > 0 ? 'text-amber-500' : ''}`}>
                  {status.election?.demotions ?? 0}
                </div>
                <div className="text-[10px] text-muted-foreground uppercase">Demotions</div>
              </div>
            </div>

            {/* Active SDOWN/ODOWN Agents */}
            {(status.health_monitor?.sdown_agents?.length ?? 0) > 0 && (
              <div className="pt-3 border-t border-border">
                <div className="text-[10px] text-muted-foreground uppercase mb-2">Agents Under Watch</div>
                <div className="flex flex-wrap gap-2">
                  {status.health_monitor?.sdown_agents?.map((id) => {
                    const isOdown = status.health_monitor?.odown_agents?.includes(id)
                    return (
                      <Badge
                        key={id}
                        className={`text-[10px] px-2 py-0.5 ${
                          isOdown
                            ? 'bg-red-500/15 text-red-500 border-red-500/30'
                            : 'bg-amber-500/15 text-amber-500 border-amber-500/30'
                        }`}
                      >
                        {isOdown ? '⬤ ODOWN' : '◯ SDOWN'}: {id}
                      </Badge>
                    )
                  })}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Redis Metrics */}
      {metrics?.redis && metrics.redis.connected === 1 && (
        <Card className="border-border bg-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              Redis Metrics
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-4 gap-4 text-center">
              <div>
                <div className="font-mono text-lg font-bold">
                  {metrics.redis.used_memory_bytes
                    ? `${(metrics.redis.used_memory_bytes / 1048576).toFixed(1)}MB`
                    : '—'}
                </div>
                <div className="text-[10px] text-muted-foreground uppercase">Memory Used</div>
              </div>
              <div>
                <div className="font-mono text-lg font-bold">
                  {metrics.redis.used_memory_peak_bytes
                    ? `${(metrics.redis.used_memory_peak_bytes / 1048576).toFixed(1)}MB`
                    : '—'}
                </div>
                <div className="text-[10px] text-muted-foreground uppercase">Peak Memory</div>
              </div>
              <div>
                <div className="font-mono text-lg font-bold">
                  {metrics.redis.used_memory_rss_bytes
                    ? `${(metrics.redis.used_memory_rss_bytes / 1048576).toFixed(1)}MB`
                    : '—'}
                </div>
                <div className="text-[10px] text-muted-foreground uppercase">RSS</div>
              </div>
              <div>
                <div className="font-mono text-lg font-bold">{metrics.redis.connected_clients ?? 0}</div>
                <div className="text-[10px] text-muted-foreground uppercase">Clients</div>
              </div>
            </div>

            {/* Throughput rates */}
            {metrics.rates && Object.keys(metrics.rates).length > 0 && (
              <div className="mt-3 pt-3 border-t border-border">
                <div className="text-[10px] text-muted-foreground uppercase mb-2 flex items-center gap-1">
                  <Gauge className="h-2.5 w-2.5" />
                  Throughput (per second)
                </div>
                <div className="flex flex-wrap gap-3">
                  {Object.entries(metrics.rates).map(([key, rate]) => (
                    <Badge key={key} variant="secondary" className="text-[10px] px-2 py-0.5 font-mono">
                      {key.replace(/_per_sec$/, '').replace(/_/g, ' ')}: {(rate as number).toFixed(2)}/s
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Rate Limiter */}
      {metrics?.rate_limiter && (
        <Card className="border-border bg-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Lock className="h-4 w-4" />
              Distributed Rate Limiter
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-4 text-center">
              <div>
                <div className="font-mono text-lg font-bold">{metrics.rate_limiter.checks}</div>
                <div className="text-[10px] text-muted-foreground uppercase">Checks</div>
              </div>
              <div>
                <div className="font-mono text-lg font-bold text-green-500">{metrics.rate_limiter.allowed}</div>
                <div className="text-[10px] text-muted-foreground uppercase">Allowed</div>
              </div>
              <div>
                <div className={`font-mono text-lg font-bold ${metrics.rate_limiter.denied > 0 ? 'text-destructive' : ''}`}>
                  {metrics.rate_limiter.denied}
                </div>
                <div className="text-[10px] text-muted-foreground uppercase">Denied</div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Config Epoch */}
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Shield className="h-3 w-3" />
        <span>Config Epoch: {status.config_epoch ?? 0}</span>
        {metrics?.uptime_seconds && (
          <span className="ml-4">
            Cluster uptime: {formatUptime(Math.floor(Date.now() / 1000 - metrics.uptime_seconds))}
          </span>
        )}
      </div>

      {/* Agent Grid */}
      <div>
        <h3 className="text-sm font-semibold mb-3">Registered Agents</h3>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {agents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </div>

        {agents.length === 0 && (
          <Card className="border-border bg-card">
            <CardContent className="flex items-center justify-center py-8 text-sm text-muted-foreground">
              No agents registered yet
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
