import { useState } from 'react'
import {
  useSystemInfo, useUsage, useBackups,
  useCreateBackup, useReloadAllPlugins, useRestartServer,
} from '@/hooks/use-admin-api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import ConfirmDialog from '@/components/shared/confirm-dialog'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import { toast } from 'sonner'

export default function SystemPage() {
  const { data: sys, isLoading } = useSystemInfo()
  const { data: usage } = useUsage()
  const { data: backups } = useBackups()
  const createBackup = useCreateBackup()
  const reloadAll = useReloadAllPlugins()
  const restart = useRestartServer()
  const [restartOpen, setRestartOpen] = useState(false)

  if (isLoading) return <CardSkeleton />

  return (
    <div className="space-y-6">
      {/* System Info */}
      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">System Information</CardTitle></CardHeader>
        <CardContent className="font-mono text-xs leading-7 text-muted-foreground">
          <div>Python: {sys?.python_version}</div>
          <div>Platform: {sys?.platform}</div>
          <div>Base: <code className="text-foreground">{sys?.base_dir}</code></div>
          <div>Skills: <code className="text-foreground">{sys?.skills_dir}</code> ({sys?.skills_count} files)</div>
          <div>Docs: <code className="text-foreground">{sys?.docs_dir}</code></div>
          <div>DB: <code className="text-foreground">{sys?.db_path}</code> ({sys?.db_size_mb} MB)</div>
        </CardContent>
      </Card>

      {/* Usage */}
      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Usage Statistics</CardTitle></CardHeader>
        <CardContent>
          {!usage?.totals?.length ? (
            <p className="text-sm text-muted-foreground">No usage data yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Model</TableHead>
                  <TableHead className="text-right">Messages</TableHead>
                  <TableHead className="text-right">Tokens In</TableHead>
                  <TableHead className="text-right">Tokens Out</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {usage.totals.map((t) => (
                  <TableRow key={t.model_used}>
                    <TableCell className="text-xs">{t.model_used}</TableCell>
                    <TableCell className="text-right font-mono text-xs">{t.message_count}</TableCell>
                    <TableCell className="text-right font-mono text-xs">{t.total_tokens_in.toLocaleString()}</TableCell>
                    <TableCell className="text-right font-mono text-xs">{t.total_tokens_out.toLocaleString()}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Server Controls */}
      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Server Controls</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-3">
            <Button variant="destructive" onClick={() => setRestartOpen(true)}>Restart Server</Button>
            <Button
              variant="secondary"
              onClick={() => reloadAll.mutate(undefined, {
                onSuccess: (d) => toast[d.success ? 'success' : 'error'](d.message ?? d.error ?? ''),
              })}
              disabled={reloadAll.isPending}
            >
              Reload All Plugins
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Restart replaces the server process. The page will reconnect automatically once it's back.
          </p>
        </CardContent>
      </Card>

      {/* Backups */}
      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Backups</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <Button
            variant="secondary"
            onClick={() => createBackup.mutate(undefined, {
              onSuccess: (d) => toast.success(`Backup created: ${d.size_mb} MB`),
              onError: () => toast.error('Backup failed'),
            })}
            disabled={createBackup.isPending}
          >
            {createBackup.isPending ? 'Creating...' : 'Create Backup Now'}
          </Button>
          {(backups ?? []).length > 0 ? (
            <div className="space-y-1">
              {backups?.map((b) => (
                <div key={b.file} className="flex items-center justify-between border-b border-border py-2 last:border-0">
                  <span className="font-mono text-xs">{b.file}</span>
                  <span className="text-xs text-muted-foreground">{b.size_mb} MB</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No backups yet.</p>
          )}
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
