import { useState, useRef, useEffect } from 'react'
import { askQuestion } from '../services/api'
import { useAppStore } from '../stores/appStore'
import RichContent from './RichContent'

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

  // Fix LLM-output literal unicode escapes like \u{26f3}
  const fixUnicodeEscapes = (text: string): string => {
    return text.replace(/\\u\{([0-9A-Fa-f]+)\}/g, (_, hex) => {
      return String.fromCodePoint(parseInt(hex, 16))
    })
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-gray-800">
        <h2 className="font-semibold">AI 数学导师</h2>
        {selectedBook && (
          <p className="text-xs text-gray-500">
            上下文：{selectedBook.title}
            {selectedBook.node_count > 0 && ` (${selectedBook.node_count} 节点, ${selectedBook.edge_count} 边)`}
          </p>
        )}
        {!selectedBookId && (
          <p className="text-xs text-gray-500">未选择书籍 — 搜索所有知识图谱</p>
        )}
      </div>

      <div className="flex-1 overflow-auto p-4 space-y-4">
        {chatMessages.length === 0 && (
          <div className="text-center text-gray-500 mt-10">
            <p className="text-3xl mb-2">🧮</p>
            <p>提问关于你书中数学知识的问题。</p>
            <p className="text-sm mt-1">例如："什么是极限？"或"证明中值定理"</p>
          </div>
        )}

        {chatMessages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[80%] rounded-lg px-4 py-2.5 text-sm whitespace-pre-wrap
                ${msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-200'}`}
            >
              <RichContent text={fixUnicodeEscapes(msg.content)} />
              {msg.refs && msg.refs.length > 0 && (
                <div className="mt-2 pt-2 border-t border-gray-700">
                  <p className="text-xs text-gray-400 mb-1">参考：</p>
                  {msg.refs.map((ref: any, j: number) => (
                    <button
                      key={j}
                      onClick={() => selectNode(ref.id)}
                      className="block text-xs text-blue-400 hover:text-blue-300 transition"
                    >
                      [{ref.type}] {ref.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-800 rounded-lg px-4 py-2.5 text-sm text-gray-400">
              Thinking...
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <div className="p-3 border-t border-gray-800">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="提问关于你的数学知识图谱..."
            className="flex-1 bg-gray-800 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
            disabled={loading}
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-sm font-medium transition"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  )
}
