import { useState } from 'react'
import { ChevronDown, ChevronRight, CheckCircle2, XCircle, Loader2, Clock } from 'lucide-react'
import type { OrchestrationState, SubAgentState } from '@/types/chat'

interface SubAgentPanelProps {
  orchestration: OrchestrationState
}

const ROLE_ICONS: Record<string, string> = {
  builder: '\ud83d\udee0\ufe0f',
  reviewer: '\ud83d\udd0d',
  researcher: '\ud83d\udd2c',
  verifier: '\u2705',
  synthesizer: '\ud83d\udcdd',
}

const STRATEGY_LABELS: Record<string, string> = {
  parallel_research: 'Parallel Research',
  build_review: 'Build + Review',
  build_review_code: 'Code Build + Review',
  verify: 'Verification',
  plan_execution: 'Plan Execution',
}

function formatDuration(ms: number | undefined): string {
  if (!ms) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function StatusIcon({ status }: { status: SubAgentState['status'] }) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 size={14} className="text-green-400" />
    case 'failed':
      return <XCircle size={14} className="text-red-400" />
    case 'running':
      return <Loader2 size={14} className="animate-spin" style={{ color: 'var(--accent)' }} />
    default:
      return <Clock size={14} style={{ color: 'var(--text-muted)' }} />
  }
}

function SubAgentCard({ agent }: { agent: SubAgentState }) {
  const [expanded, setExpanded] = useState(false)
  const hasContent = agent.content.length > 0

  return (
    <div
      className="rounded-lg border"
      style={{
        borderColor: agent.status === 'running' ? 'var(--accent)' : 'var(--border)',
        background: 'var(--bg-secondary)',
      }}
    >
      {/* Header */}
      <button
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs"
        onClick={() => hasContent && setExpanded(!expanded)}
      >
        {hasContent ? (
          expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />
        ) : (
          <span className="w-3" />
        )}

        <span>{ROLE_ICONS[agent.role] ?? '\ud83e\udd16'}</span>

        <span className="font-medium capitalize" style={{ color: 'var(--text-primary)' }}>
          {agent.role}
        </span>

        <span
          className="rounded-full px-1.5 py-0.5 text-[9px]"
          style={{
            background: 'var(--bg-tertiary)',
            color: 'var(--text-muted)',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {agent.model}
        </span>

        <span className="ml-auto flex items-center gap-1.5">
          {agent.duration_ms ? (
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
              {formatDuration(agent.duration_ms)}
            </span>
          ) : null}
          <StatusIcon status={agent.status} />
        </span>
      </button>

      {/* Expanded content */}
      {expanded && hasContent && (
        <div
          className="border-t px-3 py-2 text-xs leading-relaxed"
          style={{
            borderColor: 'var(--border)',
            color: 'var(--text-secondary)',
            maxHeight: '200px',
            overflow: 'auto',
          }}
        >
          {agent.content}
        </div>
      )}
    </div>
  )
}

export default function SubAgentPanel({ orchestration }: SubAgentPanelProps) {
  const completedCount = orchestration.agents.filter(a => a.status === 'completed').length
  const totalCount = orchestration.agents.length
  const strategyLabel = STRATEGY_LABELS[orchestration.strategy] ?? orchestration.strategy

  return (
    <div
      className="mx-4 my-3 rounded-xl border p-3"
      style={{
        borderColor: orchestration.active ? 'var(--accent)' : 'var(--border)',
        background: 'var(--bg-primary)',
        boxShadow: orchestration.active
          ? '0 0 12px rgba(var(--accent-rgb, 139, 92, 246), 0.15)'
          : 'none',
      }}
    >
      {/* Header */}
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm">{'\ud83e\udd16'}</span>
          <span className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
            {strategyLabel}
          </span>
          {orchestration.active && (
            <Loader2
              size={12}
              className="animate-spin"
              style={{ color: 'var(--accent)' }}
            />
          )}
        </div>
        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
          {completedCount}/{totalCount} agents
        </span>
      </div>

      {/* Progress bar */}
      <div
        className="mb-3 h-1 w-full overflow-hidden rounded-full"
        style={{ background: 'var(--bg-tertiary)' }}
      >
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${totalCount > 0 ? (completedCount / totalCount) * 100 : 0}%`,
            background: 'var(--accent)',
          }}
        />
      </div>

      {/* Agent cards */}
      <div className="space-y-1.5">
        {orchestration.agents.map(agent => (
          <SubAgentCard key={agent.id} agent={agent} />
        ))}
      </div>
    </div>
  )
}
