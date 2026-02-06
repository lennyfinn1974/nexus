import { useStatus, useUsage, useConversations, useCreateBackup, useRestartServer } from '@/hooks/use-admin-api'
import StatCard from '@/components/shared/stat-card'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { useState } from 'react'
import ConfirmDialog from '@/components/shared/confirm-dialog'

export default function DashboardPage() {
  const { data: status, isLoading: statusLoading } = useStatus()
  const { data: usage } = useUsage()
  const { data: conversations } = useConversations()
  const backup = useCreateBackup()
  const restart = useRestartServer()
  const [restartOpen, setRestartOpen] = useState(false)

  if (statusLoading) return <CardSkeleton />

  const totalMessages = usage?.totals?.reduce((s, t) => s + t.message_count, 0) ?? 0
  const totalTokens = usage?.totals?.reduce((s, t) => s + t.total_tokens_in + t.total_tokens_out, 0) ?? 0
  const recent = (conversations ?? []).slice(0, 5)

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <StatCard
          label="Ollama"
          value={
            <span className={status?.models.ollama_available ? 'text-success' : 'text-destructive'}>
              {status?.models.ollama_available ? 'Online' : 'Offline'}
            </span>
          }
          sub={status?.models.ollama_model}
        />
        <StatCard
          label="Claude"
          value={
            <span className={status?.models.claude_available ? 'text-success' : 'text-destructive'}>
              {status?.models.claude_available ? 'Online' : 'Offline'}
            </span>
          }
          sub={status?.models.claude_model}
        />
        <StatCard label="Plugins" value={Object.keys(status?.plugins ?? {}).length} sub="active" />
        <StatCard label="Skills" value={status?.skills_count ?? 0} sub="learned" />
        <StatCard label="Messages" value={totalMessages.toLocaleString()} sub="total" />
        <StatCard label="Tokens" value={totalTokens.toLocaleString()} sub="total used" />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="border-border bg-card">
          <CardHeader><CardTitle className="text-sm">Recent Conversations</CardTitle></CardHeader>
          <CardContent>
            {recent.length === 0 ? (
              <p className="text-sm text-muted-foreground">No conversations yet.</p>
            ) : (
              <div className="space-y-1">
                {recent.map((c) => (
                  <div key={c.id} className="flex items-center justify-between border-b border-border py-2 last:border-0">
                    <span className="truncate text-sm">{c.title || 'Untitled'}</span>
                    <span className="font-mono text-[10px] text-muted-foreground">{c.message_count} msgs</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="border-border bg-card">
          <CardHeader><CardTitle className="text-sm">Quick Actions</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <Button
              variant="secondary"
              className="w-full justify-start"
              onClick={() => {
                backup.mutate(undefined, {
                  onSuccess: (d) => toast.success(`Backup created: ${d.size_mb} MB`),
                  onError: () => toast.error('Backup failed'),
                })
              }}
              disabled={backup.isPending}
            >
              {backup.isPending ? 'Creating...' : 'Create Backup'}
            </Button>
            <Button
              variant="destructive"
              className="w-full justify-start"
              onClick={() => setRestartOpen(true)}
            >
              Restart Server
            </Button>
          </CardContent>
        </Card>
      </div>

      <ConfirmDialog
        open={restartOpen}
        onOpenChange={setRestartOpen}
        title="Restart Server?"
        description="This will briefly disconnect all clients. The page will reconnect automatically."
        confirmLabel="Restart"
        variant="destructive"
        onConfirm={() => {
          restart.mutate(undefined, {
            onSuccess: () => {
              toast.info('Server restarting...')
              setTimeout(() => window.location.reload(), 5000)
            },
          })
        }}
      />
    </div>
  )
}
