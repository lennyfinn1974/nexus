import { useCallback, useRef, useState } from 'react'
import { Send, Square } from 'lucide-react'

interface MessageInputProps {
  onSend: (content: string) => void
  onAbort: () => void
  isStreaming: boolean
  disabled?: boolean
}

export default function MessageInput({ onSend, onAbort, isStreaming, disabled }: MessageInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = useCallback(() => {
    if (!value.trim() || isStreaming || disabled) return
    onSend(value.trim())
    setValue('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }, [value, isStreaming, disabled, onSend])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  const handleInput = useCallback(() => {
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 200) + 'px'
    }
  }, [])

  return (
    <div
      className="px-4 py-3"
      style={{ borderTop: '1px solid var(--border)' }}
    >
      <div
        className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl p-2"
        style={{
          background: 'var(--bg-tertiary)',
          border: '1px solid var(--border)',
        }}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          placeholder="Message Nexus..."
          rows={1}
          className="flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none"
          style={{
            color: 'var(--text-primary)',
            maxHeight: '200px',
            fontFamily: "'DM Sans', sans-serif",
          }}
          disabled={disabled}
        />
        {isStreaming ? (
          <button
            onClick={onAbort}
            className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg transition-colors"
            style={{ background: 'var(--error)', color: '#fff' }}
            title="Stop generating"
          >
            <Square size={14} />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!value.trim() || disabled}
            className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg transition-colors"
            style={{
              background: value.trim() ? 'var(--accent)' : 'var(--bg-hover)',
              color: value.trim() ? '#fff' : 'var(--text-muted)',
              cursor: value.trim() ? 'pointer' : 'default',
            }}
            title="Send message"
          >
            <Send size={14} />
          </button>
        )}
      </div>
      <div className="mx-auto mt-1.5 max-w-3xl text-center">
        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
          Press Enter to send, Shift+Enter for new line
        </span>
      </div>
    </div>
  )
}
