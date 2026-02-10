import { useState } from 'react'
import { useAuditLog } from '@/hooks/use-admin-api'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import StatusBadge from '@/components/shared/status-badge'
import { TableSkeleton } from '@/components/shared/loading-skeleton'
import { Trash2, Plus } from 'lucide-react'

export default function SecurityPage() {
  return (
    <Tabs defaultValue="audit" className="space-y-4">
      <TabsList>
        <TabsTrigger value="audit">Audit Logs</TabsTrigger>
        <TabsTrigger value="ip">IP Blocklist</TabsTrigger>
        <TabsTrigger value="sessions">Sessions</TabsTrigger>
      </TabsList>

      <TabsContent value="audit"><AuditTab /></TabsContent>
      <TabsContent value="ip"><IpBlocklistTab /></TabsContent>
      <TabsContent value="sessions"><SessionsTab /></TabsContent>
    </Tabs>
  )
}

function AuditTab() {
  const { data, isLoading } = useAuditLog()
  const [filter, setFilter] = useState('')

  if (isLoading) return <TableSkeleton />

  const entries = (data ?? []).filter((e) =>
    !filter || e.key.toLowerCase().includes(filter.toLowerCase()) || e.changed_by.toLowerCase().includes(filter.toLowerCase())
  )

  return (
    <Card className="border-border bg-card">
      <CardHeader className="flex flex-row items-center gap-4 space-y-0">
        <CardTitle className="text-sm">Settings Change Log</CardTitle>
        <Input
          placeholder="Filter by key or actor..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="ml-auto max-w-xs"
        />
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Key</TableHead>
              <TableHead>Old Value</TableHead>
              <TableHead>New Value</TableHead>
              <TableHead>Changed By</TableHead>
              <TableHead>Timestamp</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.length === 0 ? (
              <TableRow><TableCell colSpan={5} className="text-center text-muted-foreground">No audit entries</TableCell></TableRow>
            ) : (
              entries.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="font-mono text-xs">{e.key}</TableCell>
                  <TableCell className="max-w-32 truncate text-xs text-muted-foreground">{e.old_value ?? '—'}</TableCell>
                  <TableCell className="max-w-32 truncate text-xs text-muted-foreground">{e.new_value ?? '—'}</TableCell>
                  <TableCell className="text-xs">{e.changed_by}</TableCell>
                  <TableCell className="font-mono text-[10px] text-muted-foreground">{e.changed_at}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function IpBlocklistTab() {
  const [blocked, setBlocked] = useState<string[]>([])
  const [newIp, setNewIp] = useState('')

  function addIp() {
    const ip = newIp.trim()
    if (ip && !blocked.includes(ip)) {
      setBlocked([...blocked, ip])
      setNewIp('')
    }
  }

  return (
    <Card className="border-border bg-card">
      <CardHeader>
        <CardTitle className="text-sm">IP Blocklist</CardTitle>
        <p className="text-xs text-muted-foreground">Local-only UI — will be persisted when backend endpoint is available.</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <Input
            placeholder="Enter IP address..."
            value={newIp}
            onChange={(e) => setNewIp(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addIp()}
            className="max-w-xs font-mono"
          />
          <Button size="sm" onClick={addIp}><Plus className="mr-1 h-3 w-3" />Add</Button>
        </div>
        {blocked.length === 0 ? (
          <p className="text-sm text-muted-foreground">No blocked IPs.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>IP Address</TableHead>
                <TableHead className="w-16" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {blocked.map((ip) => (
                <TableRow key={ip}>
                  <TableCell className="font-mono text-xs">{ip}</TableCell>
                  <TableCell>
                    <Button variant="ghost" size="sm" onClick={() => setBlocked(blocked.filter((b) => b !== ip))}>
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
  )
}

function SessionsTab() {
  const mockSessions = [
    { id: 'ws-abc12345', created_at: Date.now() / 1000 - 300, conv_id: 'conv-xyz', force_model: null },
    { id: 'ws-def67890', created_at: Date.now() / 1000 - 3600, conv_id: null, force_model: 'claude' },
  ]

  return (
    <Card className="border-border bg-card">
      <CardHeader>
        <CardTitle className="text-sm">Active Sessions</CardTitle>
        <p className="text-xs text-muted-foreground">Mock data — will connect to backend session API when available.</p>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Session ID</TableHead>
              <TableHead>Conversation</TableHead>
              <TableHead>Model Override</TableHead>
              <TableHead>Connected</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {mockSessions.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="font-mono text-xs">{s.id}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">{s.conv_id ?? '—'}</TableCell>
                <TableCell className="text-xs">{s.force_model ?? 'auto'}</TableCell>
                <TableCell className="font-mono text-[10px] text-muted-foreground">
                  {Math.round((Date.now() / 1000 - s.created_at) / 60)}m ago
                </TableCell>
                <TableCell><StatusBadge status="online" /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
