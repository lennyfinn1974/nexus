import { useState, useEffect, useRef, useCallback } from 'react'
import { useLogs } from '@/hooks/use-admin-api'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { LogEntry } from '@/types/api'

const levelColors: Record<string, string> = {
  INFO: 'text-success',
  WARNING: 'text-warning',
  ERROR: 'text-destructive',
  DEBUG: 'text-muted-foreground',
}

export default function LogsPage() {
  const { data: initialLogs } = useLogs()
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [filter, setFilter] = useState('all')
  const [status, setStatus] = useState('Connecting...')
  const bottomRef = useRef<HTMLDivElement>(null)
  const controllerRef = useRef<AbortController | null>(null)

  // Load initial logs
  useEffect(() => {
    if (initialLogs) setLogs(initialLogs)
  }, [initialLogs])

  // SSE stream via fetch (supports Bearer auth, unlike EventSource)
  const startStream = useCallback(() => {
    const token = sessionStorage.getItem('admin_api_key')
    if (!token) return

    const controller = new AbortController()
    controllerRef.current = controller

    fetch('/api/admin/logs/stream', {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then((res) => {
        if (!res.ok || !res.body) {
          setStatus('Failed')
          return
        }
        setStatus('Live')
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        function read(): Promise<void> {
          return reader.read().then(({ done, value }) => {
            if (done) { setStatus('Disconnected'); return }
            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() ?? ''
            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const entry: LogEntry = JSON.parse(line.slice(6))
                  setLogs((prev) => {
                    const next = [...prev, entry]
                    return next.length > 500 ? next.slice(-500) : next
                  })
                } catch { /* skip malformed */ }
              }
            }
            return read()
          })
        }
        read()
      })
      .catch((err) => {
        if (err.name !== 'AbortError') {
          setStatus('Reconnecting...')
          setTimeout(startStream, 3000)
        }
      })
  }, [])

  useEffect(() => {
    startStream()
    return () => controllerRef.current?.abort()
  }, [startStream])

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const filtered = filter === 'all' ? logs : logs.filter((l) => l.level === filter)

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Select value={filter} onValueChange={setFilter}>
          <SelectTrigger className="w-36"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Levels</SelectItem>
            <SelectItem value="ERROR">Errors</SelectItem>
            <SelectItem value="WARNING">Warnings</SelectItem>
            <SelectItem value="INFO">Info</SelectItem>
            <SelectItem value="DEBUG">Debug</SelectItem>
          </SelectContent>
        </Select>
        <Button variant="secondary" size="sm" onClick={() => setLogs([])}>Clear</Button>
        <span className={`ml-auto text-[10px] ${status === 'Live' ? 'text-success' : 'text-warning'}`}>
          {status}
        </span>
      </div>

      <Card className="border-border bg-card">
        <CardContent className="p-0">
          <ScrollArea className="h-[calc(100vh-220px)]">
            <div className="p-3 font-mono text-[11px] leading-relaxed">
              {filtered.length === 0 ? (
                <p className="text-muted-foreground">No log entries.</p>
              ) : (
                filtered.map((l, i) => {
                  const ts = l.ts?.split('T')[1]?.split('.')[0] ?? ''
                  return (
                    <div key={i} className="whitespace-pre-wrap break-all py-0.5">
                      <span className="text-muted-foreground">{ts}</span>{' '}
                      <span className={levelColors[l.level] ?? ''}>{l.level}</span>{' '}
                      {l.msg}
                    </div>
                  )
                })
              )}
              <div ref={bottomRef} />
            </div>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  )
}
