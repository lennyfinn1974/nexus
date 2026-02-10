import { useHealth } from '@/hooks/use-admin-api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import StatusBadge from '@/components/shared/status-badge'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import { Database, Cpu, Puzzle, HardDrive, MemoryStick } from 'lucide-react'
import type { HealthCheck } from '@/types/api'

interface CheckDisplay {
  key: string
  icon: typeof Database
  label: string
  check: HealthCheck
}

export default function HealthPage() {
  const { data, isLoading } = useHealth(15_000)

  if (isLoading) return <CardSkeleton />

  const checks = data?.checks
  if (!checks) return null

  const items: CheckDisplay[] = [
    { key: 'database', icon: Database, label: 'Database', check: checks.database },
    { key: 'models', icon: Cpu, label: 'AI Models', check: checks.models },
    { key: 'plugins', icon: Puzzle, label: 'Plugins', check: checks.plugins },
    { key: 'filesystem', icon: HardDrive, label: 'Filesystem', check: checks.filesystem },
    { key: 'memory', icon: MemoryStick, label: 'Memory', check: checks.memory },
  ].filter((i) => i.check)

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <StatusBadge status={data?.healthy ? 'healthy' : 'critical'} className="text-xs" />
        <span className="text-sm text-muted-foreground">Auto-refreshes every 15s</span>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {items.map(({ key, icon: Icon, label, check }) => {
          const c = check as HealthCheck & Record<string, unknown>
          const memPercent = key === 'memory' && typeof c.usage_percent === 'number' ? c.usage_percent : null
          const availMb = key === 'memory' && typeof c.available_mb === 'number' ? c.available_mb : null

          return (
            <Card key={key} className="border-border bg-card">
              <CardHeader className="flex flex-row items-center gap-3 space-y-0 pb-2">
                <Icon className="h-5 w-5 text-muted-foreground" />
                <CardTitle className="text-sm font-medium">{label}</CardTitle>
                <div className="ml-auto"><StatusBadge status={c.status} /></div>
              </CardHeader>
              <CardContent className="space-y-2">
                {c.details && <p className="text-xs text-muted-foreground">{String(c.details)}</p>}
                {key === 'models' && (
                  <div className="flex gap-4 text-xs">
                    <span>Claude: <span className={c.claude === 'available' ? 'text-success' : 'text-destructive'}>{String(c.claude ?? 'unknown')}</span></span>
                    <span>Ollama: <span className={c.ollama === 'available' ? 'text-success' : 'text-destructive'}>{String(c.ollama ?? 'unknown')}</span></span>
                  </div>
                )}
                {key === 'plugins' && (
                  <p className="text-xs text-muted-foreground">
                    {String(c.total ?? 0)} total, {String(c.errors ?? 0)} errors
                  </p>
                )}
                {memPercent !== null && (
                  <div>
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>{memPercent.toFixed(1)}% used</span>
                      {availMb !== null && <span>{(availMb / 1024).toFixed(1)} GB free</span>}
                    </div>
                    <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-secondary">
                      <div
                        className={`h-full rounded-full transition-all ${
                          memPercent > 90 ? 'bg-destructive' : memPercent > 70 ? 'bg-warning' : 'bg-success'
                        }`}
                        style={{ width: `${memPercent}%` }}
                      />
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
