import { useCallback, useEffect, useState } from 'react'
import Sidebar from '@/components/layout/sidebar'
import ChatArea from '@/components/chat/chat-area'
import { useChat } from '@/hooks/use-chat'
import type { StatusData } from '@/types/chat'

export default function App() {
  const {
    messages,
    conversations,
    currentConvId,
    isStreaming,
    streamingModel,
    orchestration,
    activeWorkCount,
    connected,
    sendMessage,
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
        onSend={sendMessage}
        onAbort={abort}
      />
    </div>
  )
}
