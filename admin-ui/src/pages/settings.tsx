import { useState, useEffect } from 'react'
import { useSettings, useUpdateSettings, useTestConnection, useRestartServer } from '@/hooks/use-admin-api'
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
import { Eye, EyeOff, FlaskConical } from 'lucide-react'
import type { SettingSchema } from '@/types/api'

const testableKeys = new Set(['ANTHROPIC_API_KEY', 'OLLAMA_BASE_URL', 'GITHUB_TOKEN'])

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
      case 'select':
        return (
          <Select value={values[s.key] ?? s.value ?? ''} onValueChange={(v) => setVal(s.key, v)}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {(s.options ?? []).map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
            </SelectContent>
          </Select>
        )
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

  return (
    <div className="space-y-6">
      {Object.entries(groups).map(([category, fields]) => (
        <Card key={category} className="border-border bg-card">
          <CardHeader><CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{category}</CardTitle></CardHeader>
          <CardContent className="space-y-5">
            {fields.map((s) => (
              <div key={s.key}>
                <Label className="text-xs font-medium">{s.label}</Label>
                <p className="mb-1.5 text-[10px] text-muted-foreground">{s.description}</p>
                {renderField(s)}
              </div>
            ))}
          </CardContent>
        </Card>
      ))}

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
