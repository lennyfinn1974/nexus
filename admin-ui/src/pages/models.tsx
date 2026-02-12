import { useState, useEffect, useCallback } from 'react'
import { useModels, useUpdateSettings, useTestConnection, useRestartServer } from '@/hooks/use-admin-api'
import { api } from '@/lib/api-client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
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
  const [claudeCodeEnabled, setClaudeCodeEnabled] = useState(false)
  const [claudeCodeModel, setClaudeCodeModel] = useState('sonnet')

  // Sub-agent settings
  const [subAgentEnabled, setSubAgentEnabled] = useState(true)
  const [subAgentAutoEnabled, setSubAgentAutoEnabled] = useState(false)
  const [subAgentMaxConcurrent, setSubAgentMaxConcurrent] = useState(4)
  const [subAgentCCConcurrent, setSubAgentCCConcurrent] = useState(2)
  const [subAgentBuilderModel, setSubAgentBuilderModel] = useState('')
  const [subAgentReviewerModel, setSubAgentReviewerModel] = useState('claude')
  const [subAgentTimeout, setSubAgentTimeout] = useState(120)

  useEffect(() => {
    if (data) {
      setClaudeModel(data.claude_model)
      setOllamaUrl(data.ollama_base_url)
      setOllamaModel(data.ollama_model)
      setThreshold(data.complexity_threshold)
      setClaudeCodeEnabled(data.claude_code_enabled ?? false)
      setClaudeCodeModel(data.claude_code_model ?? 'sonnet')

      // Sub-agent settings
      setSubAgentEnabled(data.sub_agent_enabled ?? true)
      setSubAgentAutoEnabled(data.sub_agent_auto_enabled ?? false)
      setSubAgentMaxConcurrent(data.sub_agent_max_concurrent ?? 4)
      setSubAgentCCConcurrent(data.sub_agent_cc_concurrent ?? 2)
      setSubAgentBuilderModel(data.sub_agent_builder_model ?? '')
      setSubAgentReviewerModel(data.sub_agent_reviewer_model ?? 'claude')
      setSubAgentTimeout(data.sub_agent_timeout ?? 120)
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
      CLAUDE_CODE_ENABLED: String(claudeCodeEnabled),
      CLAUDE_CODE_MODEL: claudeCodeModel,
      SUB_AGENT_ENABLED: String(subAgentEnabled),
      SUB_AGENT_AUTO_ENABLED: String(subAgentAutoEnabled),
      SUB_AGENT_MAX_CONCURRENT: String(subAgentMaxConcurrent),
      SUB_AGENT_CLAUDE_CODE_CONCURRENT: String(subAgentCCConcurrent),
      SUB_AGENT_BUILDER_MODEL: subAgentBuilderModel,
      SUB_AGENT_REVIEWER_MODEL: subAgentReviewerModel,
      SUB_AGENT_TIMEOUT: String(subAgentTimeout),
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
      <div className="grid gap-3 sm:grid-cols-4">
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
        <StatCard
          label="Claude Code"
          value={
            <span className={data?.claude_code_available ? 'text-success' : 'text-muted-foreground'}>
              {data?.claude_code_available ? 'Online' : data?.claude_code_enabled ? 'Offline' : 'Disabled'}
            </span>
          }
          sub={data?.claude_code_model ?? 'CLI agent'}
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

      {/* Claude Code Config */}
      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-sm">Claude Code (CLI Agent)</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-xs">Enable Claude Code</Label>
              <p className="text-[11px] text-muted-foreground">Agentic provider with MCP tools via Claude CLI</p>
            </div>
            <Switch checked={claudeCodeEnabled} onCheckedChange={setClaudeCodeEnabled} />
          </div>
          {claudeCodeEnabled && (
            <div>
              <Label className="text-xs">Model</Label>
              <Select value={claudeCodeModel} onValueChange={setClaudeCodeModel}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="sonnet">sonnet</SelectItem>
                  <SelectItem value="opus">opus</SelectItem>
                  <SelectItem value="haiku">haiku</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Sub-Agent System */}
      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-sm">Sub-Agent Orchestration</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-xs">Enable Sub-Agents</Label>
              <p className="text-[11px] text-muted-foreground">Spawn parallel sub-agents for complex tasks</p>
            </div>
            <Switch checked={subAgentEnabled} onCheckedChange={setSubAgentEnabled} />
          </div>
          {subAgentEnabled && (
            <>
              <div className="flex items-center justify-between">
                <div>
                  <Label className="text-xs">Auto-Detection</Label>
                  <p className="text-[11px] text-muted-foreground">Automatically detect multi-part questions and code tasks in BLD:APP</p>
                </div>
                <Switch checked={subAgentAutoEnabled} onCheckedChange={setSubAgentAutoEnabled} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-xs">Max Concurrent Agents</Label>
                  <Input
                    type="number"
                    min={1}
                    max={8}
                    value={subAgentMaxConcurrent}
                    onChange={(e) => setSubAgentMaxConcurrent(Number(e.target.value))}
                    className="font-mono"
                  />
                </div>
                <div>
                  <Label className="text-xs">Max Claude Code Concurrent</Label>
                  <Input
                    type="number"
                    min={1}
                    max={4}
                    value={subAgentCCConcurrent}
                    onChange={(e) => setSubAgentCCConcurrent(Number(e.target.value))}
                    className="font-mono"
                  />
                  <p className="mt-1 text-[10px] text-muted-foreground">Each Claude Code process uses ~200-500MB RAM</p>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-xs">Builder Model</Label>
                  <Select value={subAgentBuilderModel || '__auto__'} onValueChange={(v) => setSubAgentBuilderModel(v === '__auto__' ? '' : v)}>
                    <SelectTrigger><SelectValue placeholder="Auto" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__auto__">Auto (local-first)</SelectItem>
                      <SelectItem value="ollama">Ollama</SelectItem>
                      <SelectItem value="claude">Claude API</SelectItem>
                      <SelectItem value="claude_code">Claude Code</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-xs">Reviewer Model</Label>
                  <Select value={subAgentReviewerModel || '__auto__'} onValueChange={(v) => setSubAgentReviewerModel(v === '__auto__' ? '' : v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__auto__">Auto (local-first)</SelectItem>
                      <SelectItem value="ollama">Ollama</SelectItem>
                      <SelectItem value="claude">Claude API</SelectItem>
                      <SelectItem value="claude_code">Claude Code</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div>
                <Label className="text-xs">Timeout (seconds)</Label>
                <Input
                  type="number"
                  min={30}
                  max={600}
                  value={subAgentTimeout}
                  onChange={(e) => setSubAgentTimeout(Number(e.target.value))}
                  className="font-mono"
                />
                <p className="mt-1 text-[10px] text-muted-foreground">Claude Code agents get 300s by default. Other agents use this timeout.</p>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Routing */}
      <Card className="border-border bg-card">
        <CardHeader><CardTitle className="text-sm">Routing</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">Messages scoring above this go to Claude (or Claude Code if enabled), below to Ollama. 0 = always cloud, 100 = always local.</p>
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
