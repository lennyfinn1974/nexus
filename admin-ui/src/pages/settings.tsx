import { useState, useEffect, useCallback } from 'react'
import { useSettings, useUpdateSettings, useTestConnection, useRestartServer } from '@/hooks/use-admin-api'
import { api } from '@/lib/api-client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import ConfirmDialog from '@/components/shared/confirm-dialog'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import { toast } from 'sonner'
import { Eye, EyeOff, FlaskConical, Send, ExternalLink, Smartphone, Trash2 } from 'lucide-react'
import type { SettingSchema } from '@/types/api'

const testableKeys = new Set(['ANTHROPIC_API_KEY', 'OLLAMA_BASE_URL', 'GITHUB_TOKEN'])

// ── Telegram Pairing Types ──

interface BotInfo {
  available: boolean
  username?: string
  link?: string
  first_name?: string
  error?: string
}

interface PairingEntry {
  telegram_user_id: string
  telegram_username: string | null
  telegram_first_name: string | null
  paired_at: string
  active: boolean
  conversation_id: string | null
}

interface PairingsResponse {
  pairings: PairingEntry[]
  count: number
}

// ── Telegram Pairing Card ──

function TelegramPairingCard() {
  const [botInfo, setBotInfo] = useState<BotInfo | null>(null)
  const [pairings, setPairings] = useState<PairingEntry[]>([])
  const [telegramId, setTelegramId] = useState('')
  const [sending, setSending] = useState(false)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [botRes, pairRes] = await Promise.all([
        fetch('/api/telegram/bot-info').then(r => r.json()).catch(() => null),
        fetch('/api/telegram/pairings').then(r => r.json() as Promise<PairingsResponse>).catch(() => ({ pairings: [], count: 0 })),
      ])
      setBotInfo(botRes)
      setPairings(pairRes.pairings ?? [])
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const pairDirect = useCallback(async () => {
    if (!telegramId.trim()) return
    setSending(true)
    try {
      const res = await api.post<{ success: boolean; message: string; error?: string }>('/telegram/pair-direct', {
        telegram_user_id: telegramId.trim(),
      })
      if (res.success) {
        toast.success(res.message)
        setTelegramId('')
        refresh()
      } else {
        toast.error(res.error ?? 'Failed to pair')
      }
    } catch {
      toast.error('Failed to pair — has the user sent /start to the bot?')
    } finally {
      setSending(false)
    }
  }, [telegramId, refresh])

  const revokePairing = useCallback(async (userId: string) => {
    try {
      await api.delete(`/telegram/pairings/${userId}`)
      toast.success('Pairing revoked')
      refresh()
    } catch {
      toast.error('Failed to revoke pairing')
    }
  }, [refresh])

  if (loading) return <CardSkeleton />

  return (
    <Card className="border-border bg-card">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Smartphone className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Telegram Pairing
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Bot Status */}
        <div>
          <Label className="text-xs font-medium">Bot Status</Label>
          {botInfo?.available ? (
            <div className="mt-1 flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
              <span className="text-sm text-success">
                @{botInfo.username} — Online
              </span>
              <a
                href={botInfo.link}
                target="_blank"
                rel="noreferrer"
                className="ml-auto text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
              >
                <ExternalLink className="h-3 w-3" />
                Open in Telegram
              </a>
            </div>
          ) : (
            <div className="mt-1 flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-red-500" />
              <span className="text-sm text-destructive">
                {botInfo?.error ?? 'Bot not running — set token and restart server'}
              </span>
            </div>
          )}
        </div>

        {/* Link a Telegram Account */}
        {botInfo?.available && (
          <div>
            <Label className="text-xs font-medium">Link a Telegram Account</Label>
            <p className="mb-1.5 text-[10px] text-muted-foreground">
              Enter a Telegram User ID and click Pair Now. The user must have sent /start to the bot first.
            </p>
            <div className="flex gap-2">
              <Input
                value={telegramId}
                onChange={(e) => setTelegramId(e.target.value)}
                placeholder="Telegram User ID"
                className="font-mono"
              />
              <Button
                size="sm"
                disabled={!telegramId.trim() || sending}
                onClick={pairDirect}
              >
                <Send className="mr-1 h-3 w-3" />
                {sending ? 'Pairing...' : 'Pair Now'}
              </Button>
            </div>
            <p className="mt-1 text-[10px] text-muted-foreground">
              Find your Telegram User ID by sending /start to the bot — it shows your ID
            </p>
          </div>
        )}

        {/* Active Pairings */}
        <div>
          <Label className="text-xs font-medium">Active Pairings ({pairings.filter(p => p.active).length})</Label>
          {pairings.filter(p => p.active).length === 0 ? (
            <p className="mt-1 text-sm text-muted-foreground">No linked Telegram accounts</p>
          ) : (
            <div className="mt-2 space-y-2">
              {pairings.filter(p => p.active).map((p) => (
                <div
                  key={p.telegram_user_id}
                  className="flex items-center justify-between rounded-lg border border-border px-3 py-2"
                >
                  <div>
                    <span className="text-sm font-medium">
                      {p.telegram_first_name ?? 'Unknown'}
                    </span>
                    {p.telegram_username && (
                      <span className="ml-2 text-xs text-muted-foreground">
                        @{p.telegram_username}
                      </span>
                    )}
                    <span className="ml-2 text-xs text-muted-foreground font-mono">
                      ID: {p.telegram_user_id}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-muted-foreground">
                      Paired {new Date(p.paired_at).toLocaleDateString()}
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                      onClick={() => revokePairing(p.telegram_user_id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ── Main Settings Page ──

export default function SettingsPage() {
  const { data, isLoading } = useSettings()
  const update = useUpdateSettings()
  const test = useTestConnection()
  const restart = useRestartServer()
  const [values, setValues] = useState<Record<string, string>>({})
  const [visible, setVisible] = useState<Record<string, boolean>>({})
  const [restartOpen, setRestartOpen] = useState(false)

  useEffect(() => {
    if (data) {
      const v: Record<string, string> = {}
      for (const s of data.settings) {
        if (s.type !== 'password') v[s.key] = s.value ?? ''
      }
      setValues(v)
    }
  }, [data])

  if (isLoading) return <CardSkeleton />

  // Group by category, skip Persona (has its own page)
  const groups: Record<string, SettingSchema[]> = {}
  for (const s of data?.settings ?? []) {
    if (s.category === 'Persona') continue
    if (!groups[s.category]) groups[s.category] = []
    groups[s.category].push(s)
  }

  function save() {
    const updates: Record<string, string> = {}
    for (const s of data?.settings ?? []) {
      if (s.category === 'Persona') continue
      if (s.type === 'password') {
        if (values[s.key]) updates[s.key] = values[s.key]
      } else {
        updates[s.key] = values[s.key] ?? ''
      }
    }
    update.mutate(updates, {
      onSuccess: (d) => toast.success(d.message),
      onError: () => toast.error('Save failed'),
    })
  }

  function setVal(key: string, val: string) {
    setValues((prev) => ({ ...prev, [key]: val }))
  }

  function renderField(s: SettingSchema) {
    switch (s.type) {
      case 'select': {
        // Filter empty strings — Radix Select crashes on empty value
        const opts = (s.options ?? []).filter((o) => o !== '')
        const currentVal = values[s.key] ?? s.value ?? ''
        return (
          <Select value={currentVal || '__auto__'} onValueChange={(v) => setVal(s.key, v === '__auto__' ? '' : v)}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {(s.options ?? []).includes('') && (
                <SelectItem value="__auto__">Auto (default)</SelectItem>
              )}
              {opts.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
            </SelectContent>
          </Select>
        )
      }
      case 'range':
        return (
          <div className="space-y-2">
            <div className="text-center font-mono text-2xl font-bold text-primary">
              {values[s.key] ?? s.value ?? s.min ?? 0}
            </div>
            <Slider
              value={[parseInt(values[s.key] ?? s.value ?? String(s.min ?? 0))]}
              onValueChange={([v]) => setVal(s.key, String(v))}
              min={s.min ?? 0}
              max={s.max ?? 100}
            />
            <div className="flex justify-between text-[10px] text-muted-foreground">
              <span>{s.min ?? 0}</span>
              <span>{s.max ?? 100}</span>
            </div>
          </div>
        )
      case 'password': {
        const isVisible = visible[s.key]
        return (
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Input
                type={isVisible ? 'text' : 'password'}
                placeholder={s.has_value ? 'Value set — enter new to change' : 'Not set'}
                value={values[s.key] ?? ''}
                onChange={(e) => setVal(s.key, e.target.value)}
                className="pr-10 font-mono"
              />
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setVisible({ ...visible, [s.key]: !isVisible })}
              >
                {isVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            {testableKeys.has(s.key) && (
              <Button
                variant="secondary"
                size="sm"
                disabled={test.isPending}
                onClick={() => test.mutate(s.key, {
                  onSuccess: (d) => toast[d.success ? 'success' : 'error'](d.message ?? d.error ?? ''),
                })}
              >
                <FlaskConical className="mr-1 h-3 w-3" />Test
              </Button>
            )}
          </div>
        )
      }
      case 'textarea':
        return (
          <Textarea
            value={values[s.key] ?? ''}
            onChange={(e) => setVal(s.key, e.target.value)}
            rows={4}
          />
        )
      case 'number':
        return (
          <Input
            type="number"
            min={s.min}
            max={s.max}
            value={values[s.key] ?? ''}
            onChange={(e) => setVal(s.key, e.target.value)}
            className="font-mono"
          />
        )
      default: {
        const isTestable = testableKeys.has(s.key)
        return (
          <div className="flex gap-2">
            <Input
              value={values[s.key] ?? ''}
              onChange={(e) => setVal(s.key, e.target.value)}
              className="font-mono"
            />
            {isTestable && (
              <Button
                variant="secondary"
                size="sm"
                disabled={test.isPending}
                onClick={() => test.mutate(s.key, {
                  onSuccess: (d) => toast[d.success ? 'success' : 'error'](d.message ?? d.error ?? ''),
                })}
              >
                <FlaskConical className="mr-1 h-3 w-3" />Test
              </Button>
            )}
          </div>
        )
      }
    }
  }

  // Find the Telegram category to render inline pairing after it
  const categoryOrder = Object.keys(groups)
  const telegramCategoryIndex = categoryOrder.findIndex(
    (c) => c.toLowerCase() === 'telegram' || groups[c]?.some(s => s.key.includes('TELEGRAM'))
  )

  return (
    <div className="space-y-6">
      {categoryOrder.map((category, idx) => (
        <div key={category} className="space-y-4">
          <Card className="border-border bg-card">
            <CardHeader><CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{category}</CardTitle></CardHeader>
            <CardContent className="space-y-5">
              {groups[category].map((s) => (
                <div key={s.key}>
                  <Label className="text-xs font-medium">{s.label}</Label>
                  <p className="mb-1.5 text-[10px] text-muted-foreground">{s.description}</p>
                  {renderField(s)}
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Render Telegram Pairing card right after the Telegram settings category */}
          {idx === telegramCategoryIndex && <TelegramPairingCard />}
        </div>
      ))}

      {/* If no Telegram category found, show pairing card at the end */}
      {telegramCategoryIndex === -1 && <TelegramPairingCard />}

      <div className="flex gap-3">
        <Button onClick={save} disabled={update.isPending}>
          {update.isPending ? 'Saving...' : 'Save All Settings'}
        </Button>
        <Button variant="secondary" onClick={() => window.location.reload()}>Reload</Button>
        <Button variant="destructive" onClick={() => setRestartOpen(true)}>Restart Server</Button>
      </div>

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
