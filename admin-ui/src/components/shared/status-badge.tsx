import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

type StatusVariant = 'healthy' | 'degraded' | 'critical' | 'ok' | 'error' | 'warning' | 'offline' | 'online' | 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

const variantStyles: Record<StatusVariant, string> = {
  healthy: 'bg-success/15 text-success border-success/20',
  ok: 'bg-success/15 text-success border-success/20',
  online: 'bg-success/15 text-success border-success/20',
  completed: 'bg-success/15 text-success border-success/20',
  degraded: 'bg-warning/15 text-warning border-warning/20',
  warning: 'bg-warning/15 text-warning border-warning/20',
  pending: 'bg-warning/15 text-warning border-warning/20',
  running: 'bg-primary/15 text-primary border-primary/20',
  critical: 'bg-destructive/15 text-destructive border-destructive/20',
  error: 'bg-destructive/15 text-destructive border-destructive/20',
  failed: 'bg-destructive/15 text-destructive border-destructive/20',
  offline: 'bg-muted text-muted-foreground border-border',
  cancelled: 'bg-muted text-muted-foreground border-border',
}

export default function StatusBadge({ status, className }: { status: string; className?: string }) {
  const key = status.toLowerCase() as StatusVariant
  const style = variantStyles[key] || variantStyles.offline

  return (
    <Badge variant="outline" className={cn('font-mono text-[10px] font-semibold capitalize', style, className)}>
      {status}
    </Badge>
  )
}
