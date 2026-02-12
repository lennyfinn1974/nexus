import { useMemo } from 'react'
import { Bot, User } from 'lucide-react'
import type { Message } from '@/types/chat'

interface MessageBubbleProps {
  message: Message
  isStreaming?: boolean
}

function renderContent(content: string): string {
  if (!content) return ''

  let html = content
    // Code blocks (```...```)
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_m, lang, code) => {
      return `<pre><code class="language-${lang}">${escapeHtml(code.trim())}</code></pre>`
    })
    // Inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // Bold
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    // Headers
    .replace(/^### (.+)$/gm, '<h3 style="font-size:15px;font-weight:600;margin:12px 0 6px">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 style="font-size:16px;font-weight:700;margin:14px 0 6px">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 style="font-size:18px;font-weight:700;margin:16px 0 8px">$1</h1>')
    // Unordered lists
    .replace(/^[*-] (.+)$/gm, '<li style="margin-left:16px;list-style:disc">$1</li>')
    // Ordered lists
    .replace(/^\d+\. (.+)$/gm, '<li style="margin-left:16px;list-style:decimal">$1</li>')
    // Links
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:underline">$1</a>')
    // Horizontal rules
    .replace(/^---$/gm, '<hr style="border-color:var(--border);margin:12px 0">')
    // Paragraphs (double newline)
    .replace(/\n\n/g, '</p><p style="margin:8px 0">')
    // Single newlines to <br>
    .replace(/\n/g, '<br>')

  return `<p style="margin:4px 0">${html}</p>`
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export default function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isSystem = message.role === 'system'
  const renderedContent = useMemo(() => renderContent(message.content), [message.content])

  if (isSystem) {
    return (
      <div className="mx-auto my-3 max-w-2xl text-center">
        <div
          className="inline-block rounded-lg px-4 py-2 text-xs leading-relaxed"
          style={{ color: 'var(--text-muted)', background: 'var(--bg-tertiary)' }}
          dangerouslySetInnerHTML={{ __html: renderedContent }}
        />
      </div>
    )
  }

  return (
    <div className={`flex gap-3 px-4 py-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div
          className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg"
          style={{ background: 'var(--accent-glow)', color: 'var(--accent)' }}
        >
          <Bot size={16} />
        </div>
      )}

      <div className={`max-w-[75%] ${isUser ? 'text-right' : 'text-left'}`}>
        {/* Model badge */}
        {!isUser && message.model_used && (
          <div
            className="mb-1 text-[10px] font-medium"
            style={{ color: 'var(--text-muted)', fontFamily: "'JetBrains Mono', monospace" }}
          >
            {message.model_used}
          </div>
        )}

        <div
          className="inline-block rounded-2xl px-4 py-2.5 text-sm leading-relaxed"
          style={{
            background: isUser ? 'var(--accent)' : 'var(--bg-tertiary)',
            color: isUser ? '#fff' : 'var(--text-primary)',
            border: isUser ? 'none' : '1px solid var(--border)',
            borderRadius: isUser ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
          }}
        >
          <div
            className="prose prose-sm prose-invert max-w-none"
            dangerouslySetInnerHTML={{ __html: renderedContent }}
          />
          {isStreaming && (
            <span
              className="ml-1 inline-block h-4 w-1 animate-pulse rounded-sm"
              style={{ background: 'var(--accent)' }}
            />
          )}
        </div>
      </div>

      {isUser && (
        <div
          className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg"
          style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}
        >
          <User size={16} />
        </div>
      )}
    </div>
  )
}
