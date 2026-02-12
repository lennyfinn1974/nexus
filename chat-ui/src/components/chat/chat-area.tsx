import { useEffect, useRef } from 'react'
import { Sparkles, Download } from 'lucide-react'
import MessageBubble from './message-bubble'
import MessageInput from './message-input'
import SubAgentPanel from './sub-agent-panel'
import type { Message, OrchestrationState } from '@/types/chat'

interface ChatAreaProps {
  messages: Message[]
  isStreaming: boolean
  streamingModel: string | null
  currentConvId: string | null
  orchestration: OrchestrationState | null
  onSend: (content: string) => void
  onAbort: () => void
}

export default function ChatArea({
  messages,
  isStreaming,
  streamingModel,
  currentConvId,
  orchestration,
  onSend,
  onAbort,
}: ChatAreaProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new messages or orchestration updates
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, orchestration])

  const handleExport = (format: 'markdown' | 'json') => {
    if (!currentConvId) return
    window.open(`/api/conversations/${currentConvId}/export?format=${format}`, '_blank')
  }

  return (
    <div className="flex flex-1 flex-col" style={{ background: 'var(--bg-primary)' }}>
      {/* Top bar */}
      <div
        className="flex h-14 items-center justify-between px-4"
        style={{ borderBottom: '1px solid var(--border)' }}
      >
        <div className="flex items-center gap-2">
          <Sparkles size={16} style={{ color: 'var(--accent)' }} />
          <span className="text-sm font-medium">
            {currentConvId ? 'Chat' : 'New Conversation'}
          </span>
          {isStreaming && streamingModel && (
            <span
              className="rounded-full px-2 py-0.5 text-[10px]"
              style={{
                background: 'var(--accent-glow)',
                color: 'var(--accent)',
                fontFamily: "'JetBrains Mono', monospace",
              }}
            >
              {streamingModel}
            </span>
          )}
          {orchestration?.active && (
            <span
              className="rounded-full px-2 py-0.5 text-[10px]"
              style={{
                background: 'var(--accent-glow)',
                color: 'var(--accent)',
                fontFamily: "'JetBrains Mono', monospace",
              }}
            >
              {orchestration.agents.length} sub-agents
            </span>
          )}
        </div>
        {currentConvId && (
          <div className="flex items-center gap-1">
            <button
              onClick={() => handleExport('markdown')}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-colors"
              style={{ color: 'var(--text-muted)' }}
              title="Export as Markdown"
            >
              <Download size={12} />
              <span>.md</span>
            </button>
            <button
              onClick={() => handleExport('json')}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-colors"
              style={{ color: 'var(--text-muted)' }}
              title="Export as JSON"
            >
              <Download size={12} />
              <span>.json</span>
            </button>
          </div>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto py-4">
        {messages.length === 0 ? (
          <WelcomeScreen />
        ) : (
          messages.map((msg, i) => (
            <MessageBubble
              key={i}
              message={msg}
              isStreaming={isStreaming && i === messages.length - 1 && msg.role === 'assistant'}
            />
          ))
        )}

        {/* Sub-Agent Panel — shown during orchestration */}
        {orchestration && orchestration.agents.length > 0 && (
          <SubAgentPanel orchestration={orchestration} />
        )}

        {/* Typing indicator */}
        {isStreaming && messages[messages.length - 1]?.role !== 'assistant' && !orchestration?.active && (
          <div className="flex gap-3 px-4 py-3">
            <div
              className="flex h-8 w-8 items-center justify-center rounded-lg"
              style={{ background: 'var(--accent-glow)', color: 'var(--accent)' }}
            >
              <div className="flex gap-1">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:0ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:300ms]" />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <MessageInput
        onSend={onSend}
        onAbort={onAbort}
        isStreaming={isStreaming}
      />
    </div>
  )
}

function WelcomeScreen() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4">
      <div
        className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl text-2xl font-bold text-white"
        style={{ background: 'linear-gradient(135deg, var(--accent), #a78bfa)' }}
      >
        N
      </div>
      <h2 className="mb-2 text-xl font-bold">Welcome to Nexus</h2>
      <p className="mb-6 max-w-md text-center text-sm" style={{ color: 'var(--text-secondary)' }}>
        Your autonomous AI agent. Ask questions, run commands, search the web, manage files, and more.
      </p>
      <div className="grid grid-cols-2 gap-2">
        {[
          { cmd: '/help', desc: 'See all commands' },
          { cmd: '/skills', desc: 'View learned skills' },
          { cmd: '/docs', desc: 'Browse documents' },
          { cmd: '/model auto', desc: 'Smart model routing' },
        ].map((item) => (
          <div
            key={item.cmd}
            className="rounded-lg px-4 py-2.5 text-xs"
            style={{
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border)',
            }}
          >
            <span
              className="font-semibold"
              style={{ color: 'var(--accent)', fontFamily: "'JetBrains Mono', monospace" }}
            >
              {item.cmd}
            </span>
            <span className="ml-2" style={{ color: 'var(--text-muted)' }}>
              {item.desc}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
