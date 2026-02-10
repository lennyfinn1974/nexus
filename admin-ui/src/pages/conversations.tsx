import { useState } from 'react'
import { useConversations, useDeleteConversation, useDeleteAllConversations } from '@/hooks/use-admin-api'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import ConfirmDialog from '@/components/shared/confirm-dialog'
import { TableSkeleton } from '@/components/shared/loading-skeleton'
import { toast } from 'sonner'
import { Trash2 } from 'lucide-react'

export default function ConversationsPage() {
  const { data, isLoading } = useConversations()
  const deleteOne = useDeleteConversation()
  const deleteAll = useDeleteAllConversations()
  const [clearOpen, setClearOpen] = useState(false)

  if (isLoading) return <TableSkeleton />

  return (
    <div className="space-y-4">
      <Button
        variant="destructive"
        size="sm"
        onClick={() => setClearOpen(true)}
        disabled={!data?.length}
      >
        <Trash2 className="mr-1 h-3 w-3" />Clear All History
      </Button>

      <Card className="border-border bg-card">
        <CardContent className="pt-6">
          {!data?.length ? (
            <p className="text-sm text-muted-foreground">No conversations yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead>
                  <TableHead className="text-right">Messages</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead className="w-16" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="text-sm">{c.title || 'Untitled'}</TableCell>
                    <TableCell className="text-right font-mono text-xs">{c.message_count}</TableCell>
                    <TableCell className="font-mono text-[10px] text-muted-foreground">
                      {c.updated_at ? new Date(c.updated_at).toLocaleDateString() : '—'}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={deleteOne.isPending}
                        onClick={() => deleteOne.mutate(c.id, {
                          onSuccess: () => toast.success('Deleted'),
                        })}
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

      <ConfirmDialog
        open={clearOpen}
        onOpenChange={setClearOpen}
        title="Delete All Conversations?"
        description="This will permanently delete all conversation history. This cannot be undone."
        confirmLabel="Delete All"
        variant="destructive"
        onConfirm={() => {
          deleteAll.mutate(undefined, {
            onSuccess: (d) => toast.success(`Cleared ${d.deleted} conversations`),
          })
        }}
      />
    </div>
  )
}
