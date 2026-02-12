import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSetupStatus, useUpdateSettings, useTestConnection, useCompleteSetup } from '@/hooks/use-admin-api'
import { useAuth } from '@/contexts/auth-context'
import { api } from '@/lib/api-client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { toast } from 'sonner'
import type { OllamaListResponse } from '@/types/api'

const STEPS = ['Welcome', 'Models', 'Integrations', 'Complete'] as const

export default function SetupPage() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const { data: setupStatus } = useSetupStatus()
  const updateSettings = useUpdateSettings()
  const testConn = useTestConnection()
  const completeSetup = useCompleteSetup()

  const [step, setStep] = useState(0)

  // Step 1: Admin Key
  const [adminKey, setAdminKey] = useState('')
  const [adminKeyConfirm, setAdminKeyConfirm] = useState('')

  // Step 2: Models
  const [ollamaUrl, setOllamaUrl] = useState('http://localhost:11434')
  const [ollamaModel, setOllamaModel] = useState('')
  const [ollamaModels, setOllamaModels] = useState<{ name: string; size: number }[]>([])
  const [ollamaTested, setOllamaTested] = useState(false)
  const [claudeKey, setClaudeKey] = useState('')
  const [claudeModel, setClaudeModel] = useState('claude-sonnet-4-20250514')
  const [claudeTested, setClaudeTested] = useState(false)
  const [claudeCodeEnabled, setClaudeCodeEnabled] = useState(false)

  // Step 3: Integrations
  const [telegramToken, setTelegramToken] = useState('')
  const [githubToken, setGithubToken] = useState('')
  const [mem0Key, setMem0Key] = useState('')

  const generateKey = useCallback(() => {
    const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    let key = ''
    const arr = new Uint8Array(48)
    crypto.getRandomValues(arr)
    for (const b of arr) key += chars[b % chars.length]
    setAdminKey(key)
    setAdminKeyConfirm(key)
  }, [])

  const fetchOllamaModels = useCallback(async () => {
    try {
      const res = await api.get<OllamaListResponse>('/admin/models/ollama-list')
      if (res.success) {
        setOllamaModels(res.models)
        if (res.models.length > 0 && !ollamaModel) {
          setOllamaModel(res.models[0].name)
        }
        setOllamaTested(true)
        toast.success(`Found ${res.models.length} model(s)`)
      } else {
        toast.error(res.error ?? 'Cannot reach Ollama')
      }
    } catch {
      toast.error('Cannot reach Ollama — is it running?')
    }
  }, [ollamaModel])

  const testClaude = useCallback(() => {
    // Save key first, then test
    updateSettings.mutate(
      { ANTHROPIC_API_KEY: claudeKey, CLAUDE_MODEL: claudeModel },
      {
        onSuccess: () => {
          testConn.mutate('ANTHROPIC_API_KEY', {
            onSuccess: (d) => {
              if (d.success) {
                setClaudeTested(true)
                toast.success(d.message ?? 'Claude connected')
              } else {
                toast.error(d.error ?? 'Connection failed')
              }
            },
          })
        },
        onError: () => toast.error('Failed to save API key'),
      },
    )
  }, [claudeKey, claudeModel, updateSettings, testConn])

  const hasAtLeastOneModel = ollamaTested || claudeTested

  // Step navigation
  function canProceed(): boolean {
    switch (step) {
      case 0: return adminKey.length >= 8 && adminKey === adminKeyConfirm
      case 1: return hasAtLeastOneModel
      case 2: return true // All optional
      default: return false
    }
  }

  async function handleNext() {
    if (step === 0) {
      // Nothing to save yet — admin key is saved at completion
      setStep(1)
    } else if (step === 1) {
      // Save model settings
      const updates: Record<string, string> = {
        OLLAMA_BASE_URL: ollamaUrl,
        CLAUDE_MODEL: claudeModel,
        CLAUDE_CODE_ENABLED: String(claudeCodeEnabled),
      }
      if (ollamaModel) updates.OLLAMA_MODEL = ollamaModel
      if (claudeKey) updates.ANTHROPIC_API_KEY = claudeKey

      updateSettings.mutate(updates, {
        onSuccess: () => setStep(2),
        onError: () => toast.error('Failed to save model settings'),
      })
    } else if (step === 2) {
      // Save integration settings (only non-empty)
      const updates: Record<string, string> = {}
      if (telegramToken) updates.TELEGRAM_BOT_TOKEN = telegramToken
      if (githubToken) updates.GITHUB_TOKEN = githubToken
      if (mem0Key) updates.MEM0_API_KEY = mem0Key

      if (Object.keys(updates).length > 0) {
        updateSettings.mutate(updates, {
          onSuccess: () => setStep(3),
          onError: () => toast.error('Failed to save integration settings'),
        })
      } else {
        setStep(3)
      }
    }
  }

  async function handleComplete() {
    completeSetup.mutate(adminKey, {
      onSuccess: () => {
        // Log into admin with the new key
        login(adminKey)
        toast.success('Setup complete! Welcome to Nexus.')
        navigate('/admin', { replace: true })
      },
      onError: () => toast.error('Failed to complete setup'),
    })
  }

  // Already setup — redirect
  if (setupStatus?.setup_complete) {
    navigate('/admin', { replace: true })
    return null
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-xl space-y-6">
        {/* Header */}
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary text-2xl font-bold text-primary-foreground">
            N
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Nexus Setup</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {STEPS[step]}
            <span className="ml-2 text-xs">({step + 1}/{STEPS.length})</span>
          </p>
        </div>

        {/* Progress bar */}
        <div className="flex gap-1.5">
          {STEPS.map((_, i) => (
            <div
              key={i}
              className="h-1 flex-1 rounded-full transition-colors"
              style={{
                background: i <= step ? 'hsl(var(--primary))' : 'hsl(var(--muted))',
              }}
            />
          ))}
        </div>

        {/* Step Content */}
        {step === 0 && (
          <Card className="border-border bg-card">
            <CardHeader>
              <CardTitle className="text-base">Welcome to Nexus</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Nexus is your personal AI agent — local-first, extensible, and private.
                Let's get you set up in a few quick steps.
              </p>
              <p className="text-sm text-muted-foreground">
                First, create an admin access key. This protects the admin panel and API.
                Keep it somewhere safe — you'll need it to log in.
              </p>
              <div>
                <Label className="text-xs">Admin Access Key</Label>
                <div className="flex gap-2">
                  <Input
                    type="password"
                    placeholder="Minimum 8 characters"
                    value={adminKey}
                    onChange={(e) => setAdminKey(e.target.value)}
                    className="font-mono"
                  />
                  <Button variant="secondary" size="sm" onClick={generateKey}>
                    Generate
                  </Button>
                </div>
              </div>
              <div>
                <Label className="text-xs">Confirm Key</Label>
                <Input
                  type="password"
                  placeholder="Re-enter key"
                  value={adminKeyConfirm}
                  onChange={(e) => setAdminKeyConfirm(e.target.value)}
                  className="font-mono"
                />
                {adminKeyConfirm && adminKey !== adminKeyConfirm && (
                  <p className="mt-1 text-xs text-destructive">Keys don't match</p>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {step === 1 && (
          <div className="space-y-4">
            <Card className="border-border bg-card">
              <CardHeader>
                <CardTitle className="text-sm">Ollama (Local AI)</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  Ollama runs models locally for free. If installed, Nexus uses it as the primary provider.
                </p>
                <div>
                  <Label className="text-xs">Server URL</Label>
                  <Input
                    value={ollamaUrl}
                    onChange={(e) => setOllamaUrl(e.target.value)}
                    className="font-mono"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={fetchOllamaModels}
                  >
                    Test & Browse Models
                  </Button>
                  {ollamaTested && (
                    <span className="text-xs text-success">Connected</span>
                  )}
                </div>
                {ollamaModels.length > 0 && (
                  <div>
                    <Label className="text-xs">Select Model</Label>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {ollamaModels.map((m) => (
                        <Button
                          key={m.name}
                          variant={m.name === ollamaModel ? 'default' : 'outline'}
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() => setOllamaModel(m.name)}
                        >
                          {m.name}
                          <span className="ml-1 text-muted-foreground">
                            {(m.size / 1e9).toFixed(1)}GB
                          </span>
                        </Button>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="border-border bg-card">
              <CardHeader>
                <CardTitle className="text-sm">Claude (Cloud AI)</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  Anthropic's Claude provides powerful cloud AI. Add an API key from{' '}
                  <a
                    href="https://console.anthropic.com"
                    target="_blank"
                    rel="noreferrer"
                    className="underline"
                  >
                    console.anthropic.com
                  </a>
                  .
                </p>
                <div>
                  <Label className="text-xs">API Key</Label>
                  <Input
                    type="password"
                    placeholder="sk-ant-..."
                    value={claudeKey}
                    onChange={(e) => setClaudeKey(e.target.value)}
                    className="font-mono"
                  />
                </div>
                <div>
                  <Label className="text-xs">Model</Label>
                  <Select value={claudeModel} onValueChange={setClaudeModel}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="claude-sonnet-4-20250514">claude-sonnet-4-20250514</SelectItem>
                      <SelectItem value="claude-haiku-4-20250414">claude-haiku-4-20250414</SelectItem>
                      <SelectItem value="claude-opus-4-20250514">claude-opus-4-20250514</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={!claudeKey || testConn.isPending}
                    onClick={testClaude}
                  >
                    Test Connection
                  </Button>
                  {claudeTested && (
                    <span className="text-xs text-success">Connected</span>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card className="border-border bg-card">
              <CardContent className="flex items-center justify-between py-4">
                <div>
                  <Label className="text-xs">Claude Code (CLI Agent)</Label>
                  <p className="text-[11px] text-muted-foreground">
                    Enable if you have the Claude CLI installed
                  </p>
                </div>
                <Switch
                  checked={claudeCodeEnabled}
                  onCheckedChange={setClaudeCodeEnabled}
                />
              </CardContent>
            </Card>

            {!hasAtLeastOneModel && (
              <p className="text-center text-xs text-muted-foreground">
                Test at least one model provider to continue.
              </p>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <p className="text-center text-sm text-muted-foreground">
              These integrations are optional. You can configure them later in Settings.
            </p>

            <Card className="border-border bg-card">
              <CardHeader>
                <CardTitle className="text-sm">Telegram Bot</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  Chat with Nexus via Telegram. Create a bot with{' '}
                  <a
                    href="https://t.me/BotFather"
                    target="_blank"
                    rel="noreferrer"
                    className="underline"
                  >
                    @BotFather
                  </a>{' '}
                  and paste the token.
                </p>
                <Input
                  type="password"
                  placeholder="Bot token (optional)"
                  value={telegramToken}
                  onChange={(e) => setTelegramToken(e.target.value)}
                  className="font-mono"
                />
              </CardContent>
            </Card>

            <Card className="border-border bg-card">
              <CardHeader>
                <CardTitle className="text-sm">GitHub</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  Manage repos and issues. Generate a token at{' '}
                  <a
                    href="https://github.com/settings/tokens"
                    target="_blank"
                    rel="noreferrer"
                    className="underline"
                  >
                    GitHub Settings
                  </a>
                  .
                </p>
                <Input
                  type="password"
                  placeholder="ghp_... (optional)"
                  value={githubToken}
                  onChange={(e) => setGithubToken(e.target.value)}
                  className="font-mono"
                />
              </CardContent>
            </Card>

            <Card className="border-border bg-card">
              <CardHeader>
                <CardTitle className="text-sm">Mem0 (Memory)</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  Long-term memory via Mem0 cloud. Get a key at{' '}
                  <a
                    href="https://mem0.ai"
                    target="_blank"
                    rel="noreferrer"
                    className="underline"
                  >
                    mem0.ai
                  </a>
                  .
                </p>
                <Input
                  type="password"
                  placeholder="API key (optional)"
                  value={mem0Key}
                  onChange={(e) => setMem0Key(e.target.value)}
                  className="font-mono"
                />
              </CardContent>
            </Card>
          </div>
        )}

        {step === 3 && (
          <Card className="border-border bg-card">
            <CardHeader>
              <CardTitle className="text-base">Ready to Go</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Here's what you've configured:
              </p>
              <div className="space-y-2 text-sm">
                <SummaryRow label="Admin Key" ok />
                <SummaryRow label="Ollama" ok={ollamaTested} value={ollamaModel || undefined} />
                <SummaryRow label="Claude API" ok={claudeTested} value={claudeModel} />
                <SummaryRow label="Claude Code" ok={claudeCodeEnabled} />
                <SummaryRow label="Telegram" ok={!!telegramToken} />
                <SummaryRow label="GitHub" ok={!!githubToken} />
                <SummaryRow label="Mem0" ok={!!mem0Key} />
              </div>
              <p className="text-xs text-muted-foreground">
                You can change any of these later in the admin panel settings.
              </p>
            </CardContent>
          </Card>
        )}

        {/* Navigation */}
        <div className="flex justify-between">
          <Button
            variant="ghost"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
          >
            Back
          </Button>
          {step < 3 ? (
            <Button
              onClick={handleNext}
              disabled={!canProceed() || updateSettings.isPending}
            >
              {updateSettings.isPending ? 'Saving...' : 'Next'}
            </Button>
          ) : (
            <Button
              onClick={handleComplete}
              disabled={completeSetup.isPending}
            >
              {completeSetup.isPending ? 'Finishing...' : 'Complete Setup'}
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

function SummaryRow({ label, ok, value }: { label: string; ok: boolean; value?: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-border px-3 py-2">
      <span>{label}</span>
      <span className="flex items-center gap-2">
        {value && <span className="text-xs text-muted-foreground font-mono">{value}</span>}
        <span className={ok ? 'text-success' : 'text-muted-foreground'}>
          {ok ? 'Configured' : 'Skipped'}
        </span>
      </span>
    </div>
  )
}
