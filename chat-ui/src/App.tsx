import { Component, type ReactNode, useCallback, useEffect, useState } from 'react'
import Sidebar from '@/components/layout/sidebar'
import ChatArea from '@/components/chat/chat-area'
import { useChat } from '@/hooks/use-chat'
import type { StatusData } from '@/types/chat'

class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: '2rem', fontFamily: 'system-ui, sans-serif', maxWidth: 600 }}>
          <h1 style={{ color: '#ef4444', fontSize: '1.25rem', marginBottom: '0.5rem' }}>
            Nexus Chat — Render Error
          </h1>
          <pre style={{
            background: '#1e1e2e', color: '#cdd6f4', padding: '1rem',
            borderRadius: '0.5rem', overflow: 'auto', fontSize: '0.8rem',
            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
          }}>
            {this.state.error.message}
            {'\n\n'}
            {this.state.error.stack}
          </pre>
          <button
            onClick={() => { this.setState({ error: null }); window.location.reload() }}
            style={{
              marginTop: '1rem', padding: '0.5rem 1rem', background: '#f97316',
              color: 'white', border: 'none', borderRadius: '0.375rem', cursor: 'pointer',
            }}
          >
            Reload
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

function ChatApp() {
  const {
    messages,
    conversations,
    currentConvId,
    isStreaming,
    streamingModel,
    orchestration,
    activeWorkCount,
    claudeSessions,
    connected,
    sendMessage,
    sendToSession,
    newChat,
    loadConversation,
    deleteConversation,
    searchMessages,
    abort,
  } = useChat()

  const [status, setStatus] = useState<StatusData | null>(null)

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/status')
      if (res.ok) {
        setStatus(await res.json())
      }
    } catch {
      // ignore — status is non-critical
    }
  }, [])

  // Fetch status on mount and periodically
  useEffect(() => {
    fetchStatus()
    const interval = setInterval(fetchStatus, 30000)
    return () => clearInterval(interval)
  }, [fetchStatus])

  return (
    <div className="flex h-screen w-screen">
      <Sidebar
        conversations={conversations}
        currentConvId={currentConvId}
        connected={connected}
        status={status}
        activeWorkCount={activeWorkCount}
        onNewChat={newChat}
        onSelectConversation={loadConversation}
        onDeleteConversation={deleteConversation}
        onSearch={searchMessages}
        onSendCommand={sendMessage}
      />
      <ChatArea
        messages={messages}
        isStreaming={isStreaming}
        streamingModel={streamingModel}
        currentConvId={currentConvId}
        orchestration={orchestration}
        claudeSessions={claudeSessions}
        onSend={sendMessage}
        onAbort={abort}
        onSendToSession={sendToSession}
      />
    </div>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <ChatApp />
    </ErrorBoundary>
  )
}
