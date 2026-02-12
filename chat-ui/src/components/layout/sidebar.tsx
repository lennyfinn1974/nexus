import { useState, useCallback } from 'react'
import {
  Plus, Search, Settings, MessageSquare, X, Trash2,
  Star, FileText, CheckSquare, LayoutDashboard, Smartphone, Activity,
} from 'lucide-react'
import type { Conversation, SearchResult, StatusData } from '@/types/chat'
import PairingDialog from './pairing-dialog'

interface SidebarProps {
  conversations: Conversation[]
  currentConvId: string | null
  connected: boolean
  status: StatusData | null
  activeWorkCount: number
  onNewChat: () => void
  onSelectConversation: (id: string) => void
  onDeleteConversation: (id: string) => void
  onSearch: (query: string) => Promise<SearchResult[]>
  onSendCommand: (cmd: string) => void
}

export default function Sidebar({
  conversations,
  currentConvId,
  connected,
  status,
  activeWorkCount,
  onNewChat,
  onSelectConversation,
  onDeleteConversation,
  onSearch,
  onSendCommand,
}: SidebarProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [searchTimeout, setSearchTimeoutState] = useState<ReturnType<typeof setTimeout> | null>(null)
  const [pairingOpen, setPairingOpen] = useState(false)

  const handleSearch = useCallback((query: string) => {
    setSearchQuery(query)
    if (searchTimeout) clearTimeout(searchTimeout)

    if (!query.trim()) {
      setSearchResults([])
      setIsSearching(false)
      return
    }

    const timeout = setTimeout(async () => {
      setIsSearching(true)
      const results = await onSearch(query)
      setSearchResults(results)
    }, 300)
    setSearchTimeoutState(timeout)
  }, [onSearch, searchTimeout])

  const clearSearch = useCallback(() => {
    setSearchQuery('')
    setSearchResults([])
    setIsSearching(false)
  }, [])

  const showingSearch = searchQuery.trim().length > 0

  return (
    <aside
      className="flex h-full w-[300px] flex-shrink-0 flex-col border-r"
      style={{
        background: 'var(--bg-secondary)',
        borderColor: 'var(--border)',
      }}
    >
      {/* ── Header ── */}
      <div
        className="flex items-center gap-3 px-5 py-4"
        style={{ borderBottom: '1px solid var(--border)' }}
      >
        <div
          className="flex h-9 w-9 items-center justify-center rounded-[10px] text-white font-bold"
          style={{ background: 'linear-gradient(135deg, var(--accent), #a78bfa)' }}
        >
          N
        </div>
        <div>
          <h1 className="text-lg font-bold tracking-tight">Nexus</h1>
          <span
            className="text-[11px]"
            style={{ color: 'var(--text-muted)', fontFamily: "'JetBrains Mono', monospace" }}
          >
            v2.0
          </span>
        </div>
      </div>

      {/* ── New Chat Button ── */}
      <div className="px-4 pt-4 pb-1">
        <button
          onClick={onNewChat}
          className="flex w-full items-center justify-center gap-2 rounded-[10px] px-4 py-2.5 text-sm font-medium text-white transition-colors"
          style={{ background: 'var(--accent)' }}
        >
          <Plus size={16} />
          New Chat
        </button>
      </div>

      {/* ── Tools Section ── */}
      <div className="px-4 pt-4">
        <div className="px-2 pb-2">
          <span
            className="text-[10px] font-semibold uppercase tracking-[0.1em]"
            style={{ color: 'var(--text-muted)' }}
          >
            Tools
          </span>
        </div>
        <SidebarButton icon={<Star size={14} />} label="Skills" onClick={() => onSendCommand('/skills')} />
        <SidebarButton icon={<FileText size={14} />} label="Documents" onClick={() => onSendCommand('/docs')} />
        <SidebarButton icon={<CheckSquare size={14} />} label="Tasks" onClick={() => onSendCommand('/tasks')} />
        <SidebarButton
          icon={<Activity size={14} />}
          label={`Work Streams${activeWorkCount > 0 ? ` (${activeWorkCount})` : ''}`}
          onClick={() => { window.location.href = '/admin/workstreams' }}
          badge={activeWorkCount > 0 ? activeWorkCount : undefined}
        />
      </div>

      {/* ── System Section ── */}
      <div className="px-4 pt-4">
        <div className="px-2 pb-2">
          <span
            className="text-[10px] font-semibold uppercase tracking-[0.1em]"
            style={{ color: 'var(--text-muted)' }}
          >
            System
          </span>
        </div>
        <SidebarButton
          icon={<LayoutDashboard size={14} />}
          label="Admin"
          onClick={() => { window.location.href = '/admin' }}
        />
        <SidebarButton
          icon={<Settings size={14} />}
          label="Status"
          onClick={() => onSendCommand('/status')}
        />
        <SidebarButton
          icon={<Smartphone size={14} />}
          label="Link Telegram"
          onClick={() => setPairingOpen(true)}
        />
      </div>

      <PairingDialog open={pairingOpen} onOpenChange={setPairingOpen} />

      {/* ── Search ── */}
      <div className="px-4 pt-4">
        <div className="relative">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
            style={{ color: 'var(--text-muted)' }}
          />
          <input
            type="text"
            placeholder="Search conversations..."
            value={searchQuery}
            onChange={(e) => handleSearch(e.target.value)}
            className="w-full rounded-lg py-2.5 pl-9 pr-8 text-xs outline-none transition-colors"
            style={{
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
            }}
          />
          {searchQuery && (
            <button
              onClick={clearSearch}
              className="absolute right-3 top-1/2 -translate-y-1/2"
              style={{ color: 'var(--text-muted)' }}
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {/* ── Section Title (Recent Chats / Search Results) ── */}
      <div className="px-6 pt-4 pb-2">
        <span
          className="text-[10px] font-semibold uppercase tracking-[0.1em]"
          style={{ color: 'var(--text-muted)' }}
        >
          {showingSearch ? 'Search Results' : 'Recent Chats'}
        </span>
      </div>

      {/* ── Conversation List / Search Results ── */}
      <div className="flex-1 overflow-y-auto px-3">
        {showingSearch ? (
          isSearching && searchResults.length === 0 ? (
            <div className="py-6 text-center text-xs" style={{ color: 'var(--text-muted)' }}>
              {searchQuery.length >= 2 ? 'No results found' : 'Searching...'}
            </div>
          ) : (
            searchResults.map((r, i) => (
              <button
                key={i}
                onClick={() => {
                  clearSearch()
                  onSelectConversation(r.conversation_id)
                }}
                className="mb-1.5 w-full rounded-lg p-3 text-left transition-colors"
                style={{
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border)',
                }}
              >
                <div className="text-[11px] font-semibold" style={{ color: 'var(--accent)' }}>
                  {r.conversation_title}
                </div>
                <div
                  className="mt-1 text-[11px] leading-relaxed"
                  style={{ color: 'var(--text-secondary)' }}
                  dangerouslySetInnerHTML={{
                    __html: (r.headline || '').replace(/\*\*([^*]+)\*\*/g, '<b style="color:var(--warning)">$1</b>'),
                  }}
                />
                <div className="mt-1.5 flex justify-between text-[10px]" style={{ color: 'var(--text-muted)' }}>
                  <span>{r.created_at ? new Date(r.created_at).toLocaleDateString() : ''}</span>
                  <span>{Math.round(r.rank * 100)}% match</span>
                </div>
              </button>
            ))
          )
        ) : conversations.length === 0 ? (
          <div className="py-6 text-center text-xs" style={{ color: 'var(--text-muted)' }}>
            No conversations yet
          </div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              className="group relative mb-0.5 flex cursor-pointer items-center rounded-lg px-3 py-2.5 text-[13px] transition-colors"
              style={{
                color: conv.id === currentConvId ? 'var(--accent)' : 'var(--text-secondary)',
                background: conv.id === currentConvId ? 'var(--accent-glow)' : 'transparent',
              }}
              onClick={() => onSelectConversation(conv.id)}
              onMouseEnter={(e) => {
                if (conv.id !== currentConvId) {
                  e.currentTarget.style.background = 'var(--bg-hover)'
                }
              }}
              onMouseLeave={(e) => {
                if (conv.id !== currentConvId) {
                  e.currentTarget.style.background = 'transparent'
                }
              }}
            >
              <MessageSquare size={14} className="mr-2.5 flex-shrink-0 opacity-50" />
              <span className="flex-1 truncate">{conv.title || 'Untitled'}</span>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onDeleteConversation(conv.id)
                }}
                className="hidden group-hover:block flex-shrink-0 ml-2 p-1 rounded"
                style={{ color: 'var(--text-muted)' }}
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))
        )}
      </div>

      {/* ── Footer — Model Status ── */}
      <div
        className="px-5 py-4"
        style={{ borderTop: '1px solid var(--border)' }}
      >
        {/* Model status indicators */}
        <div
          className="flex items-center gap-4 text-[11px]"
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          <StatusDot
            label="Ollama"
            active={status?.models?.ollama_available ?? false}
          />
          <StatusDot
            label="Claude"
            active={status?.models?.claude_available ?? false}
          />
          {status?.models?.claude_code_available && (
            <StatusDot
              label="Code"
              active={true}
            />
          )}
        </div>

        {/* Connection status */}
        <div
          className="mt-3 flex items-center gap-2 text-[11px]"
          style={{ color: 'var(--text-muted)' }}
        >
          <span
            className="h-2 w-2 rounded-full flex-shrink-0"
            style={{ background: connected ? 'var(--success)' : 'var(--error)' }}
          />
          <span>{connected ? 'Connected' : 'Disconnected'}</span>
          {status && (
            <>
              <span style={{ color: 'var(--border)' }}>·</span>
              <span>{status.skills_count} skills</span>
              <span style={{ color: 'var(--border)' }}>·</span>
              <span>{Object.keys(status.plugins || {}).length} plugins</span>
            </>
          )}
        </div>
      </div>
    </aside>
  )
}

/* ── Reusable sidebar button ── */

function SidebarButton({
  icon,
  label,
  onClick,
  badge,
}: {
  icon: React.ReactNode
  label: string
  onClick: () => void
  badge?: number
}) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[13px] transition-colors"
      style={{ color: 'var(--text-secondary)' }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'var(--bg-hover)'
        e.currentTarget.style.color = 'var(--text-primary)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'transparent'
        e.currentTarget.style.color = 'var(--text-secondary)'
      }}
    >
      <span className="opacity-60">{icon}</span>
      <span className="flex-1 text-left">{label}</span>
      {badge !== undefined && badge > 0 && (
        <span
          className="flex h-5 min-w-[20px] items-center justify-center rounded-full px-1.5 text-[10px] font-semibold text-white"
          style={{ background: 'var(--accent)' }}
        >
          {badge}
        </span>
      )}
    </button>
  )
}

/* ── Status dot indicator ── */

function StatusDot({ label, active }: { label: string; active: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className="h-[7px] w-[7px] rounded-full"
        style={{
          background: active ? 'var(--success)' : 'var(--error)',
          boxShadow: active ? '0 0 6px var(--success)' : 'none',
        }}
      />
      <span style={{ color: active ? 'var(--text-secondary)' : 'var(--text-muted)' }}>
        {label}
      </span>
    </span>
  )
}
