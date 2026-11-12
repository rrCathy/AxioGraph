import { useState, useCallback, useEffect } from 'react'
import { uploadBook, listBooks, getGraph } from '../services/api'
import { useAppStore } from '../stores/appStore'
import type { Book } from '../types'
import Button from './ui/Button'
import EmptyState from './ui/EmptyState'
import { StatusBadge } from './ui/Badge'

export default function UploadBook() {
  const { books, setBooks, selectedBookId, selectBook, setGraphData } = useAppStore()
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [msg, setMsg] = useState('')

  const refreshBooks = useCallback(async () => {
    const data = await listBooks()
    setBooks(data)
  }, [setBooks])

  useEffect(() => { refreshBooks() }, [refreshBooks])

  const handleUpload = async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setMsg('仅支持 PDF 文件')
      return
    }
    setUploading(true)
    try {
      await uploadBook(file)
      await refreshBooks()
      setMsg('已导入页面，请到「工作台」逐页分析')
    }
    catch (e: any) { setMsg('上传失败: ' + e.message) }
    setUploading(false)
  }

  const loadGraph = async (bookId: string) => {
    selectBook(bookId)
    try { const data = await getGraph(bookId); setGraphData(data) }
    catch (e) { console.error(e) }
  }

  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files[0]) handleUpload(e.dataTransfer.files[0]) }}
        onClick={() => document.getElementById('file-input')?.click()}
        className={`relative border-2 border-dashed rounded-card p-10 text-center cursor-pointer transition-colors
          ${dragOver
            ? 'border-ag-cinnabar bg-ag-quoteBg'
            : 'border-ag-line2 hover:border-ag-line3 bg-ag-bg3'}`}
      >
        <input id="file-input" type="file" accept=".pdf" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) handleUpload(f) }}
        />
        {uploading ? (
          <div className="space-y-3">
            <div className="w-8 h-8 mx-auto border-2 border-ag-cinnabar border-t-transparent rounded-dot animate-spin" />
            <p className="text-ag-ink2">导入页面索引中…</p>
          </div>
        ) : (
          <>
            <div className="w-12 h-12 mx-auto mb-4 rounded-card border border-ag-line2 bg-ag-bg3 flex items-center justify-center">
              <span className="text-h2 text-ag-ink3" aria-hidden="true">PDF</span>
            </div>
            <p className="text-body font-medium text-ag-ink1">拖放 PDF 数学书至此</p>
            <p className="text-caption text-ag-ink3 mt-1.5">
              或点击浏览 — 仅导入页面，请到「工作台」逐页分析
            </p>
          </>
        )}
      </div>
      {msg && <p className="mt-2 text-caption text-ag-ink2">{msg}</p>}

      <div className="mt-10">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-caption font-medium text-ag-ink3 tracking-wider">
            我的书籍
          </h2>
          {books.length > 0 && (
            <span className="ag-mono text-caption text-ag-ink3">共 {books.length} 本</span>
          )}
        </div>

        {books.length === 0 && <EmptyState>书籍库为空 · 导入一本 PDF 以开始</EmptyState>}

        <div className="flex flex-col gap-cardgap">
          {books.map((book) => {
            const isActive = selectedBookId === book.id
            const isDone = book.status.startsWith('done')
            const hasData = book.node_count > 0 || book.edge_count > 0
            const isProcessing = book.status === 'extracting' || book.status === 'parsing' || book.status === 'checking'

            return (
              <div
                key={book.id}
                className={`group rounded-card border transition-colors
                  ${isActive
                    ? 'border-ag-cinnabar bg-ag-quoteBg'
                    : 'border-ag-line1 bg-ag-bg3 hover:border-ag-line2'}`}
              >
                <div className="p-card">
                  <div className="flex items-start gap-3">
                    <div className={`w-9 h-9 rounded-card flex items-center justify-center shrink-0 mt-0.5 border
                      ${isActive ? 'border-ag-cinnabar' : 'border-ag-line1'}`}>
                      <span className="ag-mono text-micro text-ag-ink3">PDF</span>
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <button
                          className={`text-body font-medium truncate hover:text-ag-cinnabar transition-colors
                            ${isActive ? 'text-ag-cinnabar' : 'text-ag-ink1'}`}
                          onClick={() => { if (isDone && hasData) loadGraph(book.id) }}
                          title={book.title}
                        >
                          {book.title}
                        </button>
                        <StatusBadge status={book.status} />
                      </div>
                      <p className="ag-mono text-caption text-ag-ink3 mt-0.5 truncate">
                        {book.language === 'zh' ? '中文' : '英文'} · {book.filename}
                      </p>

                      {(isDone || isProcessing) && (
                        <div className="flex items-center gap-3 mt-2 ag-mono text-caption text-ag-ink3">
                          {book.node_count > 0 && (
                            <span className="flex items-center gap-1">
                              <span className="w-1.5 h-1.5 rounded-dot bg-ag-entityDef" />
                              {book.node_count} 节点
                            </span>
                          )}
                          {book.edge_count > 0 && (
                            <span className="flex items-center gap-1">
                              <span className="w-1.5 h-1.5 rounded-dot bg-ag-entityLem" />
                              {book.edge_count} 边
                            </span>
                          )}
                          {book.node_count === 0 && book.edge_count === 0 && isDone && (
                            <span className="text-ag-ink3">未找到实体</span>
                          )}
                        </div>
                      )}
                    </div>

                    {isDone && hasData && (
                      <Button size="sm" onClick={() => { void loadGraph(book.id) }}>
                        查看图谱
                      </Button>
                    )}
                  </div>
                </div>

                {isProcessing && <ProgressBar book={book} onRefresh={refreshBooks} />}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function ProgressBar({ book }: { book: Book; onRefresh?: () => void }) {
  const done = book.chunk_done || 0
  const total = book.chunk_total || 0

  // chunk_done/chunk_total is countable: show the count, never a fake ETA.
  return (
    <div className="px-card pb-card">
      <div className="flex justify-between items-center text-caption text-ag-ink3">
        <span>
          {book.status === 'checking' && '检测 LLM 中…'}
          {book.status === 'parsing' && '解析 PDF 中…'}
          {book.status === 'paused' && `已暂停 — ${done}/${total} 块`}
          {book.status === 'extracting' && total > 0 && `已完成块 ${done}/${total}`}
          {book.status === 'extracting' && total === 0 && '准备中…'}
        </span>
        <span className="flex items-center gap-1.5 ag-mono">
          {book.node_count > 0 && <span>{book.node_count}n</span>}
          {book.edge_count > 0 && <span>{book.edge_count}e</span>}
        </span>
      </div>
    </div>
  )
}
