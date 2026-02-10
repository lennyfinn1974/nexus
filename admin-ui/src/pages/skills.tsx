import { useState } from 'react'
import { useSkills, useSkillPacks, useDeleteSkill, useInstallSkillPack } from '@/hooks/use-admin-api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import ConfirmDialog from '@/components/shared/confirm-dialog'
import StatusBadge from '@/components/shared/status-badge'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import { toast } from 'sonner'
import { Trash2, Download } from 'lucide-react'

export default function SkillsPage() {
  const { data: skills, isLoading } = useSkills()
  const { data: packs } = useSkillPacks()
  const deleteSkill = useDeleteSkill()
  const installPack = useInstallSkillPack()
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null)

  if (isLoading) return <CardSkeleton />

  return (
    <div className="space-y-6">
      {/* Installed Skills */}
      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-sm">Installed Skills</CardTitle></CardHeader>
        <CardContent>
          {!skills?.length ? (
            <p className="text-sm text-muted-foreground">No skills learned yet. Use <code>/learn &lt;topic&gt;</code> to start.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Domain</TableHead>
                  <TableHead className="text-right">Usage</TableHead>
                  <TableHead className="w-16" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {skills.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="text-sm font-medium">{s.name}</TableCell>
                    <TableCell><Badge variant="outline" className="text-[10px]">{s.type}</Badge></TableCell>
                    <TableCell className="text-xs text-muted-foreground">{s.domain}</TableCell>
                    <TableCell className="text-right font-mono text-xs">{s.usage_count ?? 0}</TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDeleteTarget({ id: s.id, name: s.name })}
                      >
                        <Trash2 className="h-3 w-3 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Skill Packs */}
      {(packs ?? []).length > 0 && (
        <Card className="border-border bg-card">
          <CardHeader><CardTitle className="text-sm">Available Skill Packs</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {packs?.map((p) => (
              <div key={p.id} className="flex items-center gap-4 rounded-lg border border-border bg-background p-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{p.name}</span>
                    <Badge variant="outline" className="text-[10px]">{p.type}</Badge>
                    {p.installed && <StatusBadge status="completed" />}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{p.description}</p>
                  {p.domain && <p className="mt-0.5 text-[10px] text-muted-foreground">Domain: {p.domain}</p>}
                  {p.config_keys.length > 0 && (
                    <p className="mt-0.5 text-[10px] text-muted-foreground">
                      Config: {p.config_keys.join(', ')}
                    </p>
                  )}
                </div>
                <Button
                  size="sm"
                  disabled={p.installed || installPack.isPending}
                  onClick={() => installPack.mutate(p.id, {
                    onSuccess: () => toast.success(`Installed ${p.name}`),
                    onError: (e) => toast.error(e.message),
                  })}
                >
                  <Download className="mr-1 h-3 w-3" />
                  {p.installed ? 'Installed' : 'Install'}
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={() => setDeleteTarget(null)}
        title="Delete Skill?"
        description={`Permanently delete "${deleteTarget?.name}". This cannot be undone.`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => {
          if (deleteTarget) {
            deleteSkill.mutate(deleteTarget.id, {
              onSuccess: () => toast.success('Skill deleted'),
            })
          }
        }}
      />
    </div>
  )
}
