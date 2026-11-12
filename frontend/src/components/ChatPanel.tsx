import { useState, useRef, useEffect } from 'react'
import { askQuestion } from '../services/api'
import { useAppStore } from '../stores/appStore'
import RichContent from './RichContent'
import Button from './ui/Button'
import EmptyState from './ui/EmptyState'

export default function ChatPanel() {
  const { chatMessages, addChatMessage, selectedBookId, books, selectNode } = useAppStore()
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const selectedBook = books.find((b) => b.id === selectedBookId)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  const handleSend = async () => {
    if (!input.trim() || loading) return
    const question = input.trim()
    setInput('')
    addChatMessage({ role: 'user', content: question })
    setLoading(true)

    try {
      const result = await askQuestion(question, selectedBookId || undefined)
      addChatMessage({
        role: 'assistant',
        content: result.answer,
        refs: result.references,
      })
    } catch (e: any) {
      addChatMessage({ role: 'assistant', content: `Error: ${e.message}` })
    }
    setLoading(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const fixUnicodeEscapes = (text: string): string => {
    return text.replace(/\\u\{([0-9A-Fa-f]+)\}/g, (_, hex) => {
      return String.fromCodePoint(parseInt(hex, 16))
    })
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="px-4 py-3 border-b border-ag-line1 bg-ag-bg1">
        <h2 className="text-h3 font-medium text-ag-ink1">AI 数学导师</h2>
        {selectedBook && (
          <p className="ag-mono text-caption text-ag-ink3">
            上下文：{selectedBook.title}
            {selectedBook.node_count > 0 && ` (${selectedBook.node_count} 节点, ${selectedBook.edge_count} 边)`}
          </p>
        )}
        {!selectedBookId && (
          <p className="text-caption text-ag-ink3">未选择书籍 — 搜索所有知识图谱</p>
        )}
      </div>

      <div className="flex-1 overflow-auto p-4 space-y-4 bg-ag-bg2">
        {chatMessages.length === 0 && (
          <div className="mt-10">
            <EmptyState>提问关于你书中数学知识的问题 · 例如“什么是极限？”</EmptyState>
          </div>
        )}

        {chatMessages.map((msg, i) => {
          const isUser = msg.role === 'user'
          return (
            <div
              key={i}
              className="border-l-2 pl-3 py-1"
              style={{ borderColor: isUser ? 'var(--ag-cinnabar)' : 'var(--ag-line-3)' }}
            >
              <p className="ag-mono text-micro text-ag-ink3 mb-1">{isUser ? '问' : '答'}</p>
              <div className="text-body text-ag-ink2 leading-relaxed max-w-measure whitespace-pre-wrap">
                <RichContent text={fixUnicodeEscapes(msg.content)} />
              </div>
              {msg.refs && msg.refs.length > 0 && (
                <div className="mt-2 pt-2 border-t border-ag-line1">
                  <p className="text-caption text-ag-ink3 mb-1">参考：</p>
                  {msg.refs.map((ref: any, j: number) => (
                    <button
                      key={j}
                      onClick={() => selectNode(ref.id)}
                      className="ag-focus-ring block text-caption text-ag-cinnabar hover:underline"
                    >
                      [{ref.type}] {ref.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )
        })}

        {loading && (
          <div className="border-l-2 border-ag-line3 pl-3 py-1">
            <span className="text-body text-ag-ink3">Thinking…</span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <div className="p-3 border-t border-ag-line1 bg-ag-bg1">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="提问关于你的数学知识图谱..."
            className="ag-focus-ring flex-1 bg-ag-bg2 rounded-btn px-4 py-2 text-body border border-ag-line2 text-ag-ink1"
            disabled={loading}
          />
          <Button variant="primary" onClick={() => void handleSend()} disabled={loading || !input.trim()}>
            发送
          </Button>
        </div>
      </div>
    </div>
  )
}
