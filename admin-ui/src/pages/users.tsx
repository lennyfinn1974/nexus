import { useState, useEffect } from 'react'
import { useSettings, useUpdateSettings, useTestConnection } from '@/hooks/use-admin-api'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import { toast } from 'sonner'
import { X, Plus, Eye, EyeOff, FlaskConical } from 'lucide-react'

export default function UsersPage() {
  return (
    <Tabs defaultValue="users" className="space-y-4">
      <TabsList>
        <TabsTrigger value="users">Allowed Users</TabsTrigger>
        <TabsTrigger value="oauth">API Keys & Tokens</TabsTrigger>
      </TabsList>

      <TabsContent value="users"><AllowedUsersTab /></TabsContent>
      <TabsContent value="oauth"><OAuthTab /></TabsContent>
    </Tabs>
  )
}

function AllowedUsersTab() {
  const { data, isLoading } = useSettings()
  const update = useUpdateSettings()
  const [users, setUsers] = useState<string[]>([])
  const [newId, setNewId] = useState('')

  useEffect(() => {
    if (data) {
      const setting = data.settings.find((s) => s.key === 'TELEGRAM_ALLOWED_USERS')
      if (setting?.value) {
        setUsers(setting.value.split(',').map((u) => u.trim()).filter(Boolean))
      }
    }
  }, [data])

  if (isLoading) return <CardSkeleton />

  function addUser() {
    const id = newId.trim()
    if (id && !users.includes(id)) {
      const next = [...users, id]
      setUsers(next)
      setNewId('')
      save(next)
    }
  }

  function removeUser(id: string) {
    const next = users.filter((u) => u !== id)
    setUsers(next)
    save(next)
  }

  function save(list: string[]) {
    update.mutate(
      { TELEGRAM_ALLOWED_USERS: list.join(',') },
      {
        onSuccess: (d) => toast.success(d.message),
        onError: () => toast.error('Failed to save'),
      }
    )
  }

  return (
    <Card className="border-border bg-card">
      <CardHeader>
        <CardTitle className="text-sm">Telegram Allowed Users</CardTitle>
        <p className="text-xs text-muted-foreground">Telegram user IDs authorized to interact with the bot.</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <Input
            placeholder="Telegram User ID..."
            value={newId}
            onChange={(e) => setNewId(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addUser()}
            className="max-w-xs font-mono"
          />
          <Button size="sm" onClick={addUser}><Plus className="mr-1 h-3 w-3" />Add</Button>
        </div>
        <div className="flex flex-wrap gap-2">
          {users.length === 0 ? (
            <p className="text-sm text-muted-foreground">No users configured. Anyone can use the bot.</p>
          ) : (
            users.map((u) => (
              <Badge key={u} variant="secondary" className="gap-1 font-mono">
                {u}
                <button onClick={() => removeUser(u)} className="ml-1 hover:text-destructive">
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  )
}

const oauthKeys = [
  { key: 'ANTHROPIC_API_KEY', label: 'Anthropic API Key', testable: true },
  { key: 'GITHUB_TOKEN', label: 'GitHub Token', testable: true },
  { key: 'TELEGRAM_BOT_TOKEN', label: 'Telegram Bot Token', testable: false },
  { key: 'OPENCLAW_TOKEN', label: 'OpenClaw Token', testable: false },
]

function OAuthTab() {
  const { data, isLoading } = useSettings()
  const update = useUpdateSettings()
  const test = useTestConnection()
  const [values, setValues] = useState<Record<string, string>>({})
  const [visible, setVisible] = useState<Record<string, boolean>>({})

  if (isLoading) return <CardSkeleton />

  return (
    <div className="space-y-4">
      {oauthKeys.map(({ key, label, testable }) => {
        const setting = data?.settings.find((s) => s.key === key)
        const hasValue = setting?.has_value ?? false

        return (
          <Card key={key} className="border-border bg-card">
            <CardContent className="pt-6">
              <div className="space-y-2">
                <Label className="text-xs font-medium">{label}</Label>
                {hasValue && <p className="text-[10px] text-success">Value is set (enter new to change)</p>}
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <Input
                      type={visible[key] ? 'text' : 'password'}
                      placeholder={hasValue ? 'Enter new value to change...' : 'Not set'}
                      value={values[key] ?? ''}
                      onChange={(e) => setValues({ ...values, [key]: e.target.value })}
                      className="pr-10 font-mono"
                    />
                    <button
                      type="button"
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      onClick={() => setVisible({ ...visible, [key]: !visible[key] })}
                    >
                      {visible[key] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                  <Button
                    size="sm"
                    disabled={!values[key] || update.isPending}
                    onClick={() => {
                      update.mutate(
                        { [key]: values[key] },
                        {
                          onSuccess: (d) => { toast.success(d.message); setValues({ ...values, [key]: '' }) },
                          onError: () => toast.error('Save failed'),
                        }
                      )
                    }}
                  >
                    Save
                  </Button>
                  {testable && (
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={test.isPending}
                      onClick={() => {
                        test.mutate(key, {
                          onSuccess: (d) => toast[d.success ? 'success' : 'error'](d.message ?? d.error ?? 'Unknown result'),
                        })
                      }}
                    >
                      <FlaskConical className="mr-1 h-3 w-3" />Test
                    </Button>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
