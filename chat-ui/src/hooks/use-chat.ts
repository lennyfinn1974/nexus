import { useCallback, useEffect, useRef, useState } from 'react'
import { useWebSocket } from './use-websocket'
import type { Message, Conversation, WSMessage, OrchestrationState } from '@/types/chat'

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [currentConvId, setCurrentConvId] = useState<string | null>(
    () => localStorage.getItem('nexus_conv_id')
  )
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingModel, setStreamingModel] = useState<string | null>(null)
  const [orchestration, setOrchestration] = useState<OrchestrationState | null>(null)
  const [activeWorkCount, setActiveWorkCount] = useState(0)
  const streamContentRef = useRef('')

  // Refs for values that callbacks need without causing re-render cycles
  const currentConvIdRef = useRef(currentConvId)
  const sendRef = useRef<(data: Record<string, unknown>) => void>(() => {})

  useEffect(() => {
    currentConvIdRef.current = currentConvId
  }, [currentConvId])

  // ── Conversation loading (via REST API) ──

  const loadConversations = useCallback(async () => {
    try {
      const res = await fetch('/api/conversations')
      if (!res.ok) return
      const data = await res.json()
      setConversations(data)
    } catch (e) {
      console.error('Failed to load conversations:', e)
    }
  }, [])

  const loadConversation = useCallback(async (convId: string) => {
    try {
      const res = await fetch(`/api/conversations/${convId}/messages`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setMessages(data.messages || [])
      setCurrentConvId(convId)
      localStorage.setItem('nexus_conv_id', convId)
      // Tell the server which conversation we're in
      sendRef.current({ type: 'set_conversation', conv_id: convId })
    } catch (e) {
      console.error('Failed to load conversation:', e)
      // Conversation might have been deleted — start fresh
      setMessages([])
      setCurrentConvId(null)
      localStorage.removeItem('nexus_conv_id')
    }
  }, [])

  // ── WebSocket message handler ──

  const handleWSMessage = useCallback((msg: WSMessage) => {
    switch (msg.type) {
      case 'stream_start':
        setIsStreaming(true)
        setStreamingModel(msg.model ?? null)
        streamContentRef.current = ''
        setMessages(prev => [
          ...prev,
          { role: 'assistant', content: '', model_used: msg.model },
        ])
        break

      case 'stream_chunk':
        streamContentRef.current += msg.content ?? ''
        setMessages(prev => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          if (last?.role === 'assistant') {
            updated[updated.length - 1] = {
              ...last,
              content: streamContentRef.current,
            }
          }
          return updated
        })
        break

      case 'stream_end':
        setIsStreaming(false)
        setStreamingModel(null)
        // Clear orchestration when streaming ends (synthesis complete)
        setOrchestration(prev => prev ? { ...prev, active: false } : null)
        if (msg.conv_id) {
          setCurrentConvId(msg.conv_id)
          localStorage.setItem('nexus_conv_id', msg.conv_id)
        }
        if (msg.title) {
          setConversations(prev =>
            prev.map(c =>
              c.id === msg.conv_id ? { ...c, title: msg.title! } : c
            )
          )
        }
        loadConversations()
        break

      case 'message':
        // Backend sends {type: "message", content: ..., model: "system"} for slash commands
        setMessages(prev => [
          ...prev,
          {
            role: 'assistant',
            content: msg.content ?? '',
            model_used: msg.model,
          },
        ])
        break

      case 'system':
        setMessages(prev => [
          ...prev,
          { role: 'system', content: msg.content ?? '' },
        ])
        break

      case 'error':
        setMessages(prev => [
          ...prev,
          { role: 'system', content: `\u26a0\ufe0f ${msg.content ?? 'Unknown error'}` },
        ])
        setIsStreaming(false)
        setOrchestration(prev => prev ? { ...prev, active: false } : null)
        break

      case 'conversation_set':
        // Server confirmed conversation switch
        if (msg.conv_id) {
          setCurrentConvId(msg.conv_id)
          localStorage.setItem('nexus_conv_id', msg.conv_id)
        }
        break

      case 'conversation_renamed':
        // Server renamed a conversation (e.g., auto-title after first message)
        if (msg.conv_id && msg.title) {
          setConversations(prev =>
            prev.map(c =>
              c.id === msg.conv_id ? { ...c, title: msg.title! } : c
            )
          )
        }
        break

      case 'ping':
        // Respond to server pings to keep connection alive
        sendRef.current({ type: 'pong' })
        break

      // ── Sub-Agent Messages ──

      case 'sub_agent_start':
        setIsStreaming(true)
        setOrchestration({
          id: msg.orchestration_id ?? '',
          strategy: msg.strategy ?? '',
          active: true,
          agents: (msg.sub_agents ?? []).map(sa => ({
            id: sa.id,
            role: sa.role,
            model: sa.model,
            status: 'pending' as const,
            content: '',
          })),
        })
        break

      case 'sub_agent_progress':
        setOrchestration(prev => {
          if (!prev) return prev
          return {
            ...prev,
            agents: prev.agents.map(a =>
              a.id === msg.sub_agent_id
                ? {
                    ...a,
                    status: 'running' as const,
                    role: msg.sub_agent_role ?? a.role,
                    content: msg.content ?? a.content,
                  }
                : a
            ),
          }
        })
        break

      case 'sub_agent_complete':
        setOrchestration(prev => {
          if (!prev) return prev
          return {
            ...prev,
            agents: prev.agents.map(a =>
              a.id === msg.sub_agent_id
                ? {
                    ...a,
                    status: (msg.sub_agent_status === 'completed' ? 'completed' : 'failed') as 'completed' | 'failed',
                    model: msg.sub_agent_model ?? a.model,
                    content: msg.content ?? a.content,
                    duration_ms: msg.duration_ms,
                  }
                : a
            ),
          }
        })
        break

      // ── Work Item Tracking ──

      case 'work_item_update': {
        const item = msg.item
        if (!item) break
        const isActive = item.status === 'running' || item.status === 'pending'
        const isTerminal = item.status === 'completed' || item.status === 'failed' || item.status === 'cancelled'

        if (msg.event === 'registered' && isActive) {
          setActiveWorkCount(prev => prev + 1)
        } else if (msg.event === 'updated' && isTerminal) {
          setActiveWorkCount(prev => Math.max(0, prev - 1))
        }
        break
      }
    }
  }, [loadConversations])

  // ── WebSocket connection ──

  const { connected, send } = useWebSocket({
    onMessage: handleWSMessage,
    onOpen: () => {
      loadConversations()
      const savedConvId = currentConvIdRef.current
      if (savedConvId) {
        // Restore conversation from last session
        loadConversation(savedConvId)
      }
    },
  })

  // Keep sendRef in sync
  useEffect(() => {
    sendRef.current = send
  }, [send])

  // ── Actions ──

  const sendMessage = useCallback((content: string) => {
    if (!content.trim() || isStreaming) return

    // Clear any previous orchestration state
    setOrchestration(null)

    // Add user message to UI immediately
    setMessages(prev => [...prev, { role: 'user', content }])

    // Send via WebSocket — backend expects "text" field, not "content"
    send({ type: 'chat', text: content })
  }, [isStreaming, send])

  const newChat = useCallback(() => {
    setMessages([])
    setCurrentConvId(null)
    setOrchestration(null)
    localStorage.removeItem('nexus_conv_id')
    // Tell server to create a new conversation
    send({ type: 'set_conversation' })
  }, [send])

  const switchConversation = useCallback((convId: string) => {
    setOrchestration(null)
    loadConversation(convId)
  }, [loadConversation])

  const deleteConversation = useCallback(async (convId: string) => {
    try {
      await fetch(`/api/conversations/${convId}`, { method: 'DELETE' })
      setConversations(prev => prev.filter(c => c.id !== convId))
      if (convId === currentConvIdRef.current) {
        setMessages([])
        setCurrentConvId(null)
        localStorage.removeItem('nexus_conv_id')
      }
    } catch (e) {
      console.error('Failed to delete conversation:', e)
    }
  }, [])

  const searchMessages = useCallback(async (query: string) => {
    if (!query.trim()) return []
    try {
      const res = await fetch(`/api/conversations/search?q=${encodeURIComponent(query)}&limit=20`)
      if (!res.ok) return []
      const data = await res.json()
      return data.results || []
    } catch {
      return []
    }
  }, [])

  const abort = useCallback(() => {
    send({ type: 'abort' })
    setIsStreaming(false)
    setOrchestration(prev => prev ? { ...prev, active: false } : null)
  }, [send])

  return {
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
    loadConversation: switchConversation,
    deleteConversation,
    searchMessages,
    abort,
    loadConversations,
  }
}
