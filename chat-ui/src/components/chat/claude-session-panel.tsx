import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, CheckCircle2, XCircle, Loader2, Send, Terminal, DollarSign, Clock, Wrench } from 'lucide-react'
import type { ClaudeSessionState } from '@/types/chat'

interface ClaudeSessionPanelProps {
  sessions: Record<string, ClaudeSessionState>
  onSendToSession: (sessionId: string, text: string) => void
}

function formatDuration(ms: number): string {
  if (!ms) return ''
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}

function formatCost(usd: number): string {
  if (!usd) return ''
  return `$${usd.toFixed(4)}`
}

function SessionCard({
  session,
  onSend,
}: {
  session: ClaudeSessionState
  onSend: (text: string) => void
}) {
  const [expanded, setExpanded] = useState(session.status === 'running')
  const [input, setInput] = useState('')
  const outputRef = useRef<HTMLPreElement>(null)

  // Auto-scroll output when new content arrives
  useEffect(() => {
    if (outputRef.current && expanded) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [session.output, expanded])

  // Auto-expand when running
  useEffect(() => {
    if (session.status === 'running') {
      setExpanded(true)
    }
  }, [session.status])

  const handleSend = () => {
    if (!input.trim() || session.status !== 'running') return
    onSend(input.trim())
    setInput('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const isRunning = session.status === 'running'
  const isComplete = session.status === 'completed'
  const isFailed = session.status === 'failed'

  return (
    <div
      className="rounded-lg border"
      style={{
        borderColor: isRunning ? 'var(--accent)' : 'var(--border)',
        background: 'var(--bg-secondary)',
        boxShadow: isRunning
          ? '0 0 8px rgba(var(--accent-rgb, 139, 92, 246), 0.1)'
          : 'none',
      }}
    >
      {/* Header */}
      <button
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}

        <Terminal size={14} style={{ color: 'var(--accent)' }} />

        <span className="font-medium" style={{ color: 'var(--text-primary)' }}>
          {session.name || session.id}
        </span>

        {session.role && (
          <span
            className="rounded-full px-1.5 py-0.5 text-[9px] font-medium"
            style={{
              background: 'var(--accent)',
              color: 'white',
              opacity: 0.85,
            }}
          >
            {session.role}
          </span>
        )}

        <span
          className="rounded-full px-1.5 py-0.5 text-[9px]"
          style={{
            background: 'var(--bg-tertiary)',
            color: 'var(--text-muted)',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {session.id}
        </span>

        <span className="ml-auto flex items-center gap-2">
          {session.toolsUsed.length > 0 && (
            <span className="flex items-center gap-0.5 text-[10px]" style={{ color: 'var(--text-muted)' }}>
              <Wrench size={10} />
              {session.toolsUsed.length}
            </span>
          )}
          {session.costUsd > 0 && (
            <span className="flex items-center gap-0.5 text-[10px]" style={{ color: 'var(--text-muted)' }}>
              <DollarSign size={10} />
              {formatCost(session.costUsd)}
            </span>
          )}
          {session.durationMs > 0 && (
            <span className="flex items-center gap-0.5 text-[10px]" style={{ color: 'var(--text-muted)' }}>
              <Clock size={10} />
              {formatDuration(session.durationMs)}
            </span>
          )}
          {isRunning && <Loader2 size={14} className="animate-spin" style={{ color: 'var(--accent)' }} />}
          {isComplete && <CheckCircle2 size={14} className="text-green-400" />}
          {isFailed && <XCircle size={14} className="text-red-400" />}
        </span>
      </button>

      {/* Expanded content */}
      {expanded && (
        <>
          {/* Tool badges */}
          {session.toolsUsed.length > 0 && (
            <div
              className="flex flex-wrap gap-1 border-t px-3 py-1.5"
              style={{ borderColor: 'var(--border)' }}
            >
              {session.toolsUsed.map(tool => (
                <span
                  key={tool}
                  className="rounded px-1.5 py-0.5 text-[9px]"
                  style={{
                    background: 'var(--bg-tertiary)',
                    color: 'var(--text-muted)',
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                >
                  {tool}
                </span>
              ))}
            </div>
          )}

          {/* Terminal output */}
          <pre
            ref={outputRef}
            className="border-t px-3 py-2 text-[11px] leading-relaxed"
            style={{
              borderColor: 'var(--border)',
              color: '#a6e3a1',
              background: '#11111b',
              maxHeight: '400px',
              overflow: 'auto',
              fontFamily: "'JetBrains Mono', 'Fira Code', 'SF Mono', monospace",
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {session.output || (isRunning ? 'Waiting for output...' : '(no output)')}
          </pre>

          {/* Follow-up input (only when running) */}
          {isRunning && (
            <div
              className="flex items-center gap-2 border-t px-3 py-2"
              style={{ borderColor: 'var(--border)' }}
            >
              <input
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Send follow-up..."
                className="flex-1 rounded-md border-none bg-transparent px-2 py-1 text-xs outline-none"
                style={{
                  color: 'var(--text-primary)',
                  background: 'var(--bg-tertiary)',
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              />
              <button
                onClick={handleSend}
                disabled={!input.trim()}
                className="flex items-center justify-center rounded-md p-1.5 transition-colors"
                style={{
                  background: input.trim() ? 'var(--accent)' : 'var(--bg-tertiary)',
                  color: input.trim() ? 'white' : 'var(--text-muted)',
                  cursor: input.trim() ? 'pointer' : 'default',
                }}
              >
                <Send size={12} />
              </button>
            </div>
          )}

          {/* Completion footer */}
          {!isRunning && (session.costUsd > 0 || session.durationMs > 0) && (
            <div
              className="flex items-center justify-between border-t px-3 py-1.5 text-[10px]"
              style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}
            >
              <span>{isComplete ? 'Completed' : 'Failed'}</span>
              <span className="flex items-center gap-3">
                {session.durationMs > 0 && <span>{formatDuration(session.durationMs)}</span>}
                {session.costUsd > 0 && <span>{formatCost(session.costUsd)}</span>}
              </span>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default function ClaudeSessionPanel({ sessions, onSendToSession }: ClaudeSessionPanelProps) {
  const sessionList = Object.values(sessions)

  if (sessionList.length === 0) return null

  const runningCount = sessionList.filter(s => s.status === 'running').length
  const totalCount = sessionList.length

  return (
    <div
      className="mx-4 my-3 rounded-xl border p-3"
      style={{
        borderColor: runningCount > 0 ? 'var(--accent)' : 'var(--border)',
        background: 'var(--bg-primary)',
        boxShadow: runningCount > 0
          ? '0 0 12px rgba(var(--accent-rgb, 139, 92, 246), 0.15)'
          : 'none',
      }}
    >
      {/* Header */}
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Terminal size={14} style={{ color: 'var(--accent)' }} />
          <span className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
            Claude Code Sessions
          </span>
          {runningCount > 0 && (
            <Loader2
              size={12}
              className="animate-spin"
              style={{ color: 'var(--accent)' }}
            />
          )}
        </div>
        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
          {runningCount > 0 ? `${runningCount} running` : `${totalCount} session${totalCount !== 1 ? 's' : ''}`}
        </span>
      </div>

      {/* Session cards */}
      <div className="space-y-1.5">
        {sessionList.map(session => (
          <SessionCard
            key={session.id}
            session={session}
            onSend={(text) => onSendToSession(session.id, text)}
          />
        ))}
      </div>
    </div>
  )
}
