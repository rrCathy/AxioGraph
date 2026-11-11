import { useState, useCallback, useEffect } from 'react'
import { uploadBook, listBooks, getGraph, pauseExtraction, resumeExtraction, cancelExtraction } from '../services/api'
import { useAppStore } from '../stores/appStore'
import type { Book } from '../types'

export default function UploadBook() {
  const { books, setBooks, selectedBookId, selectBook, setGraphData } = useAppStore()
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [pollIds, setPollIds] = useState<Set<string>>(new Set())

  const refreshBooks = useCallback(async () => {
    const data = await listBooks()
    setBooks(data)
    const processing = data.filter((b: Book) =>
      b.status === 'checking' || b.status === 'pending' || b.status === 'parsing' || b.status === 'extracting'
    )
    if (processing.length > 0) {
      setPollIds(new Set(processing.map((b: Book) => b.id)))
    } else {
      setPollIds(new Set())
    }
  }, [setBooks])

  useEffect(() => { refreshBooks() }, [refreshBooks])

  useEffect(() => {
    if (pollIds.size === 0) return
    const timer = setInterval(refreshBooks, 1500)
    return () => clearInterval(timer)
  }, [pollIds, refreshBooks])

  const handleUpload = async (file: File) => {
    if (!file.name.endsWith('.pdf')) {
      alert('仅支持PDF文件')
      return
    }
    setUploading(true)
    try { await uploadBook(file); await refreshBooks() }
    catch (e: any) { alert('上传失败: ' + e.message) }
    setUploading(false)
  }

  const loadGraph = async (bookId: string) => {
    selectBook(bookId)
    try { const data = await getGraph(bookId); setGraphData(data) }
    catch (e) { console.error(e) }
  }

  return (
    <div>
      {/* ─── Upload Zone ───────────────────────────── */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files[0]) handleUpload(e.dataTransfer.files[0]) }}
        onClick={() => document.getElementById('file-input')?.click()}
        className={`relative border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all duration-200
          ${dragOver
            ? 'border-accent-blue bg-accent-blue/5 scale-[1.01]'
            : 'border-border-medium hover:border-border-strong bg-surface-card/50 hover:bg-surface-card'}`}
      >
        <input id="file-input" type="file" accept=".pdf" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) handleUpload(f) }}
        />
        {uploading ? (
          <div className="space-y-3">
            <div className="w-8 h-8 mx-auto border-2 border-accent-blue border-t-transparent rounded-full animate-spin" />
            <p className="text-text-secondary">上传中...</p>
          </div>
        ) : (
          <>
            <div className="w-14 h-14 mx-auto mb-4 rounded-xl bg-surface-hover flex items-center justify-center">
              <span className="text-2xl opacity-60">{'\u{1F4E5}'}</span>
            </div>
            <p className="text-base font-medium text-text-primary">
              拖放PDF数学书至此
            </p>
            <p className="text-sm text-text-muted mt-1.5">
              或点击浏览 — 将提取定义、定理和证明
            </p>
          </>
        )}
      </div>

      {/* ─── Book List ─────────────────────────────── */}
      <div className="mt-10">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-text-muted uppercase tracking-wider">
            我的书籍
          </h2>
          {books.length > 0 && (
            <span className="text-2xs text-text-dim">共 {books.length} 本</span>
          )}
        </div>

        {books.length === 0 && (
          <div className="text-center py-12 text-text-dim">
            <p className="text-2xl mb-2 opacity-30">{'\u{1F4D6}'}</p>
            <p className="text-sm">暂无导入书籍。</p>
          </div>
        )}

        <div className="space-y-2">
          {books.map((book) => {
            const isActive = selectedBookId === book.id
            const isDone = book.status.startsWith('done')
            const hasData = book.node_count > 0 || book.edge_count > 0
            const isProcessing = book.status === 'extracting' || book.status === 'parsing' || book.status === 'checking'

            return (
              <div
                key={book.id}
                className={`group rounded-xl border transition-all duration-150
                  ${isActive
                    ? 'border-accent-blue/40 bg-accent-blue/5'
                    : 'border-border-subtle bg-surface-card hover:border-border-medium'}`}
              >
                <div className="p-3.5">
                  <div className="flex items-start gap-3">
                    {/* Book icon */}
                    <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 mt-0.5
                      ${isProcessing ? 'bg-accent-purple/15' : isDone ? 'bg-accent-green/10' : 'bg-surface-hover'}`}>
                      <span className="text-base">{'\u{1F4D8}'}</span>
                    </div>

                    {/* Book info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p
                          className={`font-medium text-sm truncate cursor-pointer hover:text-accent-blue transition-colors
                            ${isActive ? 'text-accent-blue' : 'text-text-primary'}`}
                          onClick={() => { if (isDone && hasData) loadGraph(book.id) }}
                          title={book.title}
                        >
                          {book.title}
                        </p>
                        <StatusBadge status={book.status} />
                      </div>
                      <p className="text-2xs text-text-dim mt-0.5 truncate">
                        {book.language === 'zh' ? '中文' : '英文'} · {book.filename}
                      </p>

                      {/* Stats row */}
                      {(isDone || isProcessing) && (
                        <div className="flex items-center gap-3 mt-2 text-2xs text-text-muted">
                          {book.node_count > 0 && (
                            <span className="flex items-center gap-1">
                              <span className="w-1.5 h-1.5 rounded-full bg-accent-green" />
                              {book.node_count} 节点
                            </span>
                          )}
                          {book.edge_count > 0 && (
                            <span className="flex items-center gap-1">
                              <span className="w-1.5 h-1.5 rounded-full bg-accent-purple" />
                              {book.edge_count} 边
                            </span>
                          )}
                          {book.node_count === 0 && book.edge_count === 0 && isDone && (
                            <span className="text-text-dim">未找到实体</span>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1 shrink-0">
                      {isDone && hasData && (
                        <button
                          onClick={(e) => { e.stopPropagation(); loadGraph(book.id) }}
                          className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-all duration-150
                            ${isActive
                              ? 'bg-accent-blue/20 text-accent-blue'
                              : 'bg-surface-hover text-text-secondary hover:bg-accent-blue/15 hover:text-accent-blue'}`}
                        >
                          查看图谱
                        </button>
                      )}
                    </div>
                  </div>
                </div>

                {/* Progress bar */}
                {isProcessing && (
                  <ProgressBar book={book} onRefresh={refreshBooks} />
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function ProgressBar({ book, onRefresh }: { book: Book; onRefresh: () => void }) {
  const pct = book.progress || 0
  const done = book.chunk_done || 0
  const total = book.chunk_total || 0
  const nodes = book.node_count || 0
  const edges = book.edge_count || 0
  const isPaused = book.status === 'paused'

  const etaText = done > 0 && total > 0
    ? formatETA((Date.now() - (Date.now() - 1000)) / done * (total - done))
    : ''

  return (
    <div className="px-3.5 pb-3">
      <div className="w-full h-1 bg-surface-hover rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ease-out
            ${isPaused ? 'bg-accent-amber' : 'bg-accent-purple'}`}
          style={{ width: `${Math.max(pct, 2)}%` }}
        />
      </div>
      <div className="flex justify-between items-center mt-1.5 text-2xs text-text-dim">
        <span>
          {book.status === 'checking' && '检测LLM中...'}
          {book.status === 'parsing' && '解析PDF中...'}
          {book.status === 'paused' && `已暂停 — ${done}/${total} 块`}
          {book.status === 'extracting' && total > 0 && `块 ${done}/${total} · ${pct}%`}
          {book.status === 'extracting' && total === 0 && '准备中...'}
        </span>
        <span className="flex items-center gap-1.5">
          {nodes > 0 && <span>{nodes}n</span>}
          {edges > 0 && <span>{edges}e</span>}
          <span className="flex gap-0.5 ml-1">
            {!isPaused && book.status === 'extracting' && (
              <button onClick={async (e) => { e.stopPropagation(); try { await pauseExtraction(book.id) } catch {}; onRefresh() }}
                className="text-accent-amber hover:text-amber-300">暂停</button>
            )}
            {isPaused && (
              <button onClick={async (e) => { e.stopPropagation(); try { await resumeExtraction(book.id) } catch {}; onRefresh() }}
                className="text-accent-green hover:text-green-300">继续</button>
            )}
            {(book.status === 'extracting' || isPaused) && (
              <button onClick={async (e) => { e.stopPropagation(); try { await cancelExtraction(book.id) } catch {}; onRefresh() }}
                className="text-accent-red/70 hover:text-accent-red ml-1">取消</button>
            )}
          </span>
        </span>
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const isDone = status.startsWith('done')
  const isError = status.startsWith('error')
  const isChecking = status === 'checking'

  let colorClass = 'bg-surface-hover text-text-dim'
  let label = status

  if (isChecking) { colorClass = 'bg-accent-amber/20 text-accent-amber'; label = '检测中' }
  else if (status === 'ready') { colorClass = 'bg-accent-green/15 text-accent-green'; label = '待逐页分析' }
  else if (status === 'importing') { colorClass = 'bg-accent-blue/15 text-accent-blue'; label = '导入页面中' }
  else if (status === 'pending') { colorClass = 'bg-accent-amber/15 text-accent-amber'; label = '排队中' }
  else if (status === 'parsing') { colorClass = 'bg-orange-500/20 text-orange-400'; label = '解析中' }
  else if (status === 'extracting') { colorClass = 'bg-accent-purple/20 text-accent-purple'; label = '提取中' }
  else if (isDone && status.includes('no math')) { colorClass = 'bg-surface-hover text-text-dim'; label = '空' }
  else if (isDone) { colorClass = 'bg-accent-green/15 text-accent-green'; label = '完成' }
  else if (isError) { colorClass = 'bg-accent-red/15 text-accent-red'; label = '错误' }
  else if (status === 'paused') { colorClass = 'bg-accent-amber/15 text-accent-amber'; label = '已暂停' }

  return (
    <span className={`px-1.5 py-0.5 text-2xs font-medium rounded ${colorClass}`}>
      {label}
    </span>
  )
}

function formatETA(seconds: number): string {
  if (seconds <= 0) return ''
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}
