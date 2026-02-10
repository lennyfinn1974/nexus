import { useState, useEffect, useCallback } from 'react'
import { useModels, useUpdateSettings, useTestConnection, useRestartServer } from '@/hooks/use-admin-api'
import { api } from '@/lib/api-client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import StatCard from '@/components/shared/stat-card'
import ConfirmDialog from '@/components/shared/confirm-dialog'
import { CardSkeleton } from '@/components/shared/loading-skeleton'
import { toast } from 'sonner'
import type { OllamaListResponse } from '@/types/api'

export default function ModelsPage() {
  const { data, isLoading } = useModels()
  const update = useUpdateSettings()
  const testConn = useTestConnection()
  const restart = useRestartServer()
  const [restartOpen, setRestartOpen] = useState(false)

  const [claudeModel, setClaudeModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [ollamaUrl, setOllamaUrl] = useState('')
  const [ollamaModel, setOllamaModel] = useState('')
  const [threshold, setThreshold] = useState(60)
  const [ollamaModels, setOllamaModels] = useState<{ name: string; size: number }[]>([])

  useEffect(() => {
    if (data) {
      setClaudeModel(data.claude_model)
      setOllamaUrl(data.ollama_base_url)
      setOllamaModel(data.ollama_model)
      setThreshold(data.complexity_threshold)
    }
  }, [data])

  const fetchOllamaModels = useCallback(async () => {
    try {
      const res = await api.get<OllamaListResponse>('/admin/models/ollama-list')
      if (res.success) setOllamaModels(res.models)
      else toast.error(res.error ?? 'Failed to fetch models')
    } catch {
      toast.error('Cannot reach Ollama')
    }
  }, [])

  if (isLoading) return <CardSkeleton />

  function save() {
    const updates: Record<string, string> = {
      CLAUDE_MODEL: claudeModel,
      OLLAMA_BASE_URL: ollamaUrl,
      OLLAMA_MODEL: ollamaModel,
      COMPLEXITY_THRESHOLD: String(threshold),
    }
    if (apiKey) updates.ANTHROPIC_API_KEY = apiKey

    update.mutate(updates, {
      onSuccess: (d) => { toast.success(d.message); setApiKey('') },
      onError: () => toast.error('Save failed'),
    })
  }

  return (
    <div className="space-y-6">
      {/* Status */}
      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard
          label="Claude"
          value={<span className={data?.claude_available ? 'text-success' : 'text-destructive'}>{data?.claude_available ? 'Online' : 'Offline'}</span>}
          sub={data?.claude_model}
        />
        <StatCard
          label="Ollama"
          value={<span className={data?.ollama_available ? 'text-success' : 'text-destructive'}>{data?.ollama_available ? 'Online' : 'Offline'}</span>}
          sub={data?.ollama_model}
        />
        <StatCard label="Routing" value={data?.complexity_threshold ?? 60} sub="threshold" />
      </div>

      {/* Claude Config */}
      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-sm">Claude (Cloud)</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label className="text-xs">Model</Label>
            <Select value={claudeModel} onValueChange={setClaudeModel}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="claude-sonnet-4-20250514">claude-sonnet-4-20250514</SelectItem>
                <SelectItem value="claude-haiku-4-20250414">claude-haiku-4-20250414</SelectItem>
                <SelectItem value="claude-opus-4-20250514">claude-opus-4-20250514</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">API Key</Label>
            <Input
              type="password"
              placeholder={data?.claude_available ? 'Key set (enter new to change)' : 'sk-ant-...'}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="font-mono"
            />
          </div>
          <Button
            variant="secondary"
            size="sm"
            disabled={testConn.isPending}
            onClick={() => testConn.mutate('ANTHROPIC_API_KEY', {
              onSuccess: (d) => toast[d.success ? 'success' : 'error'](d.message ?? d.error ?? ''),
            })}
          >
            Test Claude
          </Button>
        </CardContent>
      </Card>

      {/* Ollama Config */}
      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-sm">Ollama (Local)</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label className="text-xs">Server URL</Label>
            <Input value={ollamaUrl} onChange={(e) => setOllamaUrl(e.target.value)} className="font-mono" />
          </div>
          <div>
            <Label className="text-xs">Model</Label>
            <div className="flex gap-2">
              <Input value={ollamaModel} onChange={(e) => setOllamaModel(e.target.value)} className="font-mono" />
              <Button variant="secondary" size="sm" onClick={fetchOllamaModels}>Browse</Button>
            </div>
            {ollamaModels.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {ollamaModels.map((m) => (
                  <Button
                    key={m.name}
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={() => setOllamaModel(m.name)}
                  >
                    {m.name} <span className="ml-1 text-muted-foreground">{(m.size / 1e9).toFixed(1)}GB</span>
                  </Button>
                ))}
              </div>
            )}
          </div>
          <Button
            variant="secondary"
            size="sm"
            disabled={testConn.isPending}
            onClick={() => testConn.mutate('OLLAMA_BASE_URL', {
              onSuccess: (d) => toast[d.success ? 'success' : 'error'](d.message ?? d.error ?? ''),
            })}
          >
            Test Ollama
          </Button>
        </CardContent>
      </Card>

      {/* Routing */}
      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-sm">Routing</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">Messages scoring above this go to Claude, below to Ollama. 0 = always Claude, 100 = always local.</p>
          <div className="text-center font-mono text-3xl font-bold text-primary">{threshold}</div>
          <Slider value={[threshold]} onValueChange={([v]) => setThreshold(v)} min={0} max={100} step={1} />
          <div className="flex justify-between text-[10px] text-muted-foreground">
            <span>Always Claude</span>
            <span>Always Local</span>
          </div>
        </CardContent>
      </Card>

      {/* Actions */}
      <div className="flex gap-3">
        <Button onClick={save} disabled={update.isPending}>
          {update.isPending ? 'Saving...' : 'Save & Apply'}
        </Button>
        <Button variant="destructive" onClick={() => setRestartOpen(true)}>
          Restart Server
        </Button>
      </div>
      <p className="text-[11px] text-muted-foreground">Model changes take effect immediately — restart only needed if connections are stale.</p>

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
