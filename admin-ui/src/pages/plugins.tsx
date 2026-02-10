import { usePlugins, useReloadPlugin, useReloadAllPlugins, useRestartServer } from '@/hooks/use-admin-api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import StatusBadge from '@/components/shared/status-badge'
import ConfirmDialog from '@/components/shared/confirm-dialog'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import { toast } from 'sonner'
import { useState } from 'react'

export default function PluginsPage() {
  const { data, isLoading } = usePlugins()
  const reloadOne = useReloadPlugin()
  const reloadAll = useReloadAllPlugins()
  const restart = useRestartServer()
  const [restartOpen, setRestartOpen] = useState(false)

  if (isLoading) return <CardSkeleton />

  return (
    <div className="space-y-6">
      <div className="flex gap-3">
        <Button
          onClick={() => reloadAll.mutate(undefined, {
            onSuccess: (d) => toast[d.success ? 'success' : 'error'](d.message ?? d.error ?? ''),
          })}
          disabled={reloadAll.isPending}
        >
          {reloadAll.isPending ? 'Reloading...' : 'Reload All Plugins'}
        </Button>
        <Button variant="destructive" onClick={() => setRestartOpen(true)}>Restart Server</Button>
      </div>

      {/* Active Plugins */}
      {(data?.active ?? []).map((p) => {
        const isOk = p.health?.status === 'ok'
        return (
          <Card key={p.name} className="border-border bg-card">
            <CardHeader className="flex flex-row items-center gap-3 space-y-0">
              <CardTitle className="text-sm">{p.name}</CardTitle>
              <StatusBadge status={isOk ? 'ok' : 'error'} />
              <span className="ml-auto font-mono text-[10px] text-muted-foreground">v{p.version}</span>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-muted-foreground">{p.description}</p>
              <p className="font-mono text-[10px] text-muted-foreground">
                {p.tools.length} tools, {p.commands.length} commands
              </p>
              {!isOk && p.health?.message && (
                <p className="text-xs text-destructive">{p.health.message}</p>
              )}
              {p.tools.length > 0 && (
                <div className="rounded-md bg-background p-3 font-mono text-[11px] text-muted-foreground max-h-32 overflow-y-auto">
                  {p.tools.map((t) => (
                    <div key={t.name} className="py-0.5">
                      <strong className="text-foreground">{t.name}</strong> — {t.description}
                    </div>
                  ))}
                </div>
              )}
              {p.commands.length > 0 && (
                <p className="text-[10px] text-muted-foreground">
                  Commands: {p.commands.map((c) => c.command).join(', ')}
                </p>
              )}
              <Button
                variant="secondary"
                size="sm"
                disabled={reloadOne.isPending}
                onClick={() => reloadOne.mutate(p.name, {
                  onSuccess: (d) => toast[d.success ? 'success' : 'error'](d.message ?? d.error ?? ''),
                })}
              >
                Reload
              </Button>
            </CardContent>
          </Card>
        )
      })}

      {/* Available (inactive) Plugins */}
      {(data?.available ?? []).map((p) => (
        <Card key={p.name} className="border-border/50 bg-card">
          <CardHeader className="flex flex-row items-center gap-3 space-y-0">
            <CardTitle className="text-sm text-muted-foreground">{p.name}</CardTitle>
            <StatusBadge status="offline" />
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-muted-foreground">{p.reason}</p>
            <p className="font-mono text-[10px] text-muted-foreground">File: {p.file}</p>
            <Button
              size="sm"
              onClick={() => reloadOne.mutate(p.name, {
                onSuccess: (d) => {
                  if (d.success) toast.success(d.message)
                  else {
                    let msg = d.error ?? 'Unknown error'
                    if (msg.includes('setup() returned False')) msg += ' — check Settings for required API keys.'
                    toast.error(msg)
                  }
                },
              })}
            >
              Activate
            </Button>
          </CardContent>
        </Card>
      ))}

      {!data?.active?.length && !data?.available?.length && (
        <p className="text-sm text-muted-foreground">No plugins found.</p>
      )}

      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Create a Plugin</CardTitle></CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Create a <code className="text-foreground">yourname_plugin.py</code> in <code className="text-foreground">backend/plugins/</code>,
            extend <code className="text-foreground">NexusPlugin</code>, configure any API keys in Settings, then click Reload All Plugins.
          </p>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={restartOpen}
        onOpenChange={setRestartOpen}
        title="Restart Server?"
        description="This will briefly disconnect all clients."
        confirmLabel="Restart"
        variant="destructive"
        onConfirm={() => {
          restart.mutate(undefined, {
            onSuccess: () => { toast.info('Restarting...'); setTimeout(() => window.location.reload(), 5000) },
          })
        }}
      />
    </div>
  )
}
