import { useState, useEffect, useCallback } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Copy, Check, X, Smartphone, Send, ExternalLink } from 'lucide-react'

interface PairingDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

interface PairingData {
  code: string
  expires_at: string
  ttl_seconds: number
  sent?: boolean
  error?: string
  message?: string
}

interface BotInfo {
  available: boolean
  username?: string
  link?: string
  error?: string
}

export default function PairingDialog({ open, onOpenChange }: PairingDialogProps) {
  const [pairing, setPairing] = useState<PairingData | null>(null)
  const [botInfo, setBotInfo] = useState<BotInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const [secondsLeft, setSecondsLeft] = useState(0)
  const [telegramId, setTelegramId] = useState('')
  const [sentSuccess, setSentSuccess] = useState(false)

  const fetchBotInfo = useCallback(async () => {
    try {
      const res = await fetch('/api/telegram/bot-info')
      if (res.ok) {
        const data = await res.json()
        setBotInfo(data)
      }
    } catch {
      // Not critical — bot info is optional
    }
  }, [])

  const generateCode = useCallback(async () => {
    setLoading(true)
    setError('')
    setSentSuccess(false)
    try {
      const res = await fetch('/api/telegram/generate-code', { method: 'POST' })
      if (!res.ok) throw new Error('Failed to generate code')
      const data = await res.json()
      setPairing(data)
      setSecondsLeft(data.ttl_seconds)
    } catch (e: any) {
      setError(e.message || 'Failed to generate pairing code')
    } finally {
      setLoading(false)
    }
  }, [])

  const sendToTelegram = useCallback(async () => {
    if (!telegramId.trim()) return
    setSending(true)
    setError('')
    setSentSuccess(false)
    try {
      const res = await fetch('/api/telegram/send-pairing', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ telegram_user_id: telegramId.trim() }),
      })
      const data = await res.json()
      if (data.sent) {
        setPairing(data)
        setSecondsLeft(data.ttl_seconds)
        setSentSuccess(true)
      } else {
        // Code was generated but sending failed — show the code with the error
        setPairing(data)
        setSecondsLeft(data.ttl_seconds)
        setError(data.error || 'Failed to send to Telegram')
      }
    } catch (e: any) {
      setError(e.message || 'Failed to send pairing code')
    } finally {
      setSending(false)
    }
  }, [telegramId])

  // Fetch bot info & generate code when dialog opens
  useEffect(() => {
    if (open) {
      setPairing(null)
      setCopied(false)
      setError('')
      setSentSuccess(false)
      fetchBotInfo()
      generateCode()
    }
  }, [open, generateCode, fetchBotInfo])

  // Countdown timer
  useEffect(() => {
    if (!pairing || secondsLeft <= 0) return
    const timer = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1) {
          clearInterval(timer)
          return 0
        }
        return s - 1
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [pairing, secondsLeft])

  const copyCode = useCallback(() => {
    if (!pairing) return
    navigator.clipboard.writeText(`/pair ${pairing.code}`)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [pairing])

  const expired = secondsLeft <= 0 && pairing !== null

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay
          className="fixed inset-0 z-50"
          style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }}
        />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-[440px] -translate-x-1/2 -translate-y-1/2 rounded-2xl p-6"
          style={{
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border)',
            boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5)',
          }}
        >
          <div className="flex items-center justify-between mb-5">
            <div className="flex items-center gap-3">
              <div
                className="flex h-10 w-10 items-center justify-center rounded-xl"
                style={{ background: 'var(--accent-glow)' }}
              >
                <Smartphone size={20} style={{ color: 'var(--accent)' }} />
              </div>
              <Dialog.Title className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
                Link Telegram
              </Dialog.Title>
            </div>
            <Dialog.Close asChild>
              <button
                className="rounded-lg p-2 transition-colors"
                style={{ color: 'var(--text-muted)' }}
              >
                <X size={18} />
              </button>
            </Dialog.Close>
          </div>

          {/* Bot info link */}
          {botInfo?.available && botInfo.link && (
            <a
              href={botInfo.link}
              target="_blank"
              rel="noreferrer"
              className="mb-4 flex items-center gap-2 rounded-lg px-3 py-2 text-xs transition-colors"
              style={{
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border)',
                color: 'var(--accent)',
              }}
            >
              <ExternalLink size={14} />
              Open @{botInfo.username} in Telegram
              <span style={{ color: 'var(--text-muted)', marginLeft: 'auto' }}>
                Must send /start first
              </span>
            </a>
          )}

          {error && !pairing ? (
            <div
              className="rounded-lg p-4 text-sm"
              style={{ background: 'rgba(239,68,68,0.1)', color: 'var(--error)' }}
            >
              {error}
              <button
                onClick={generateCode}
                className="ml-2 underline"
              >
                Retry
              </button>
            </div>
          ) : loading ? (
            <div className="py-8 text-center" style={{ color: 'var(--text-muted)' }}>
              Generating pairing code...
            </div>
          ) : pairing ? (
            <div>
              {/* Sent success banner */}
              {sentSuccess && (
                <div
                  className="mb-4 rounded-lg px-4 py-3 text-sm"
                  style={{ background: 'rgba(34,197,94,0.1)', color: 'var(--success)' }}
                >
                  Pairing code sent to Telegram! Check your messages and reply with the /pair command.
                </div>
              )}

              {/* Error banner (when code exists but send failed) */}
              {error && (
                <div
                  className="mb-4 rounded-lg px-4 py-3 text-sm"
                  style={{ background: 'rgba(239,68,68,0.1)', color: 'var(--error)' }}
                >
                  {error}
                </div>
              )}

              {/* Code display */}
              <div
                className="mb-4 rounded-xl p-5 text-center"
                style={{
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border)',
                }}
              >
                <div
                  className="text-[32px] font-bold tracking-[0.3em]"
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    color: expired ? 'var(--text-muted)' : 'var(--accent)',
                    textDecoration: expired ? 'line-through' : 'none',
                  }}
                >
                  {pairing.code}
                </div>
                <div
                  className="mt-2 text-xs"
                  style={{ color: expired ? 'var(--error)' : 'var(--text-muted)' }}
                >
                  {expired ? 'Code expired' : `Expires in ${Math.floor(secondsLeft / 60)}:${String(secondsLeft % 60).padStart(2, '0')}`}
                </div>
              </div>

              {/* Send to Telegram */}
              {!expired && (
                <div
                  className="mb-4 rounded-lg p-4"
                  style={{
                    background: 'var(--bg-tertiary)',
                    border: '1px solid var(--border)',
                  }}
                >
                  <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>
                    Send code directly to Telegram
                  </div>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={telegramId}
                      onChange={(e) => setTelegramId(e.target.value)}
                      placeholder="Telegram User ID"
                      className="flex-1 rounded-lg px-3 py-2 text-sm"
                      style={{
                        background: 'var(--bg-primary)',
                        border: '1px solid var(--border)',
                        color: 'var(--text-primary)',
                        fontFamily: "'JetBrains Mono', monospace",
                      }}
                    />
                    <button
                      onClick={sendToTelegram}
                      disabled={!telegramId.trim() || sending}
                      className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors disabled:opacity-40"
                      style={{ background: 'var(--accent)' }}
                    >
                      <Send size={14} />
                      {sending ? 'Sending...' : 'Send'}
                    </button>
                  </div>
                  <div className="mt-1.5 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                    Find your ID by sending /start to @userinfobot on Telegram
                  </div>
                </div>
              )}

              {/* Manual instructions */}
              <div
                className="mb-4 space-y-2 text-sm"
                style={{ color: 'var(--text-secondary)' }}
              >
                <p className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
                  Or pair manually:
                </p>
                <div
                  className="flex items-center justify-between rounded-lg px-4 py-2.5"
                  style={{
                    background: 'var(--bg-tertiary)',
                    border: '1px solid var(--border)',
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: '13px',
                  }}
                >
                  <span style={{ color: 'var(--text-primary)' }}>/pair {pairing.code}</span>
                  <button
                    onClick={copyCode}
                    className="ml-3 rounded p-1 transition-colors"
                    style={{ color: 'var(--text-muted)' }}
                  >
                    {copied ? <Check size={16} style={{ color: 'var(--success)' }} /> : <Copy size={16} />}
                  </button>
                </div>
              </div>

              {/* Regenerate if expired */}
              {expired && (
                <button
                  onClick={generateCode}
                  className="w-full rounded-lg px-4 py-2.5 text-sm font-medium text-white transition-colors"
                  style={{ background: 'var(--accent)' }}
                >
                  Generate New Code
                </button>
              )}
            </div>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
