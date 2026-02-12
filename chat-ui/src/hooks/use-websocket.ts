import { useCallback, useEffect, useRef, useState } from 'react'
import type { WSMessage } from '@/types/chat'

interface UseWebSocketOptions {
  onMessage: (msg: WSMessage) => void
  onOpen?: () => void
  onClose?: () => void
}

export function useWebSocket({ onMessage, onOpen, onClose }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // Store callbacks in refs to avoid reconnect cycles when they change
  const onMessageRef = useRef(onMessage)
  const onOpenRef = useRef(onOpen)
  const onCloseRef = useRef(onClose)
  onMessageRef.current = onMessage
  onOpenRef.current = onOpen
  onCloseRef.current = onClose

  const connect = useCallback(() => {
    // Don't connect if already open or connecting
    if (wsRef.current?.readyState === WebSocket.OPEN ||
        wsRef.current?.readyState === WebSocket.CONNECTING) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const ws = new WebSocket(`${protocol}//${host}/ws/chat`)

    ws.onopen = () => {
      setConnected(true)
      onOpenRef.current?.()
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        onMessageRef.current(data)
      } catch {
        console.error('Failed to parse WS message:', event.data)
      }
    }

    ws.onclose = () => {
      setConnected(false)
      onCloseRef.current?.()
      // Auto-reconnect after 2s
      reconnectTimer.current = setTimeout(connect, 2000)
    }

    ws.onerror = () => {
      ws.close()
    }

    wsRef.current = ws
  }, []) // Empty deps — callbacks are accessed via refs

  const send = useCallback((data: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  const disconnect = useCallback(() => {
    clearTimeout(reconnectTimer.current)
    wsRef.current?.close()
    wsRef.current = null
  }, [])

  useEffect(() => {
    connect()
    return () => disconnect()
  }, [connect, disconnect])

  return { connected, send, disconnect }
}
