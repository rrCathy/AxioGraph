import Button from '../ui/Button'
import EmptyState from '../ui/EmptyState'
import { EntityBadge } from '../ui/Badge'
import type { ConfirmedNode, TextBlock } from '../../types'
import type { LongTaskState } from '../../hooks/useLongTask'
import { pageImageUrl } from '../../services/api'

export function QuoteStrip({ quote, onClear }: { quote: string; onClear: () => void }) {
  return (
    <div className="shrink-0 flex items-center gap-2 px-3 py-1.5 border-b border-ag-line1 bg-ag-bg2">
      {quote ? (
        <>
          <span className="ag-quote-index shrink-0">[1]</span>
          <span className="ag-quote flex-1 text-caption text-ag-ink2 truncate">“{quote.slice(0, 140)}”</span>
          <button onClick={onClear} className="ag-focus-ring text-caption text-ag-ink3 hover:text-ag-ink1 shrink-0">
            清除
          </button>
        </>
      ) : (
        <span className="text-caption text-ag-ink3 ag-mono">— 尚未挂引用 —</span>
      )}
    </div>
  )
}

export function PageSheet({
  bookId, pageNo, blocks, quote, pageWidth, pageHeight, onBlockClick,
}: {
  bookId: string
  pageNo: number
  blocks: TextBlock[]
  quote: string
  pageWidth?: number
  pageHeight?: number
  onBlockClick: () => void
}) {
  const key = quote.slice(0, 12)
  const hit = quote && pageWidth && pageHeight
    ? blocks.find((b) => b.text.includes(key))
    : null

  return (
    <div className="ag-page-well flex-1 overflow-auto">
      <div className="shrink-0 text-caption text-ag-ink3 mb-3 ag-mono">
        原页为图像，划选请在右侧「提取文本」中进行
      </div>
      <div className="page-sheet">
        <div className="relative">
          <img src={pageImageUrl(bookId, pageNo)} alt={`第 ${pageNo} 页原页`} draggable={false} />
          {hit && (
            <button
              onClick={onBlockClick}
              aria-label="跳回右侧对应的引用文本"
              className="ag-quote-block ag-focus-ring"
              style={{
                left: `${(hit.x0 / pageWidth!) * 100}%`,
                top: `${(hit.y0 / pageHeight!) * 100}%`,
                width: `${((hit.x1 - hit.x0) / pageWidth!) * 100}%`,
                height: `${((hit.y1 - hit.y0) / pageHeight!) * 100}%`,
              }}
            >
              <span className="ag-quote-tag">[1]</span>
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export function LongTaskStatus({
  state, elapsedLabel, onCancel,
}: {
  state: LongTaskState
  elapsedLabel: string
  onCancel: () => void
}) {
  if (!state.active) return null
  const anchor = state.kind === 'extract' ? '通常需 13–75 秒' : ''
  return (
    <div className="shrink-0 flex items-center gap-2 px-3 py-1.5 border-b border-ag-line1 bg-ag-bg2">
      <span className="inline-block w-1.5 h-1.5 rounded-dot bg-ag-cinnabar animate-pulse" aria-hidden="true" />
      <span className="text-caption text-ag-ink2">{state.phase}</span>
      <span className="ag-mono text-caption text-ag-ink3">{elapsedLabel}</span>
      {anchor && <span className="text-caption text-ag-ink3">{anchor}</span>}
      {state.softExceeded && <span className="text-caption text-ag-statusOcr">比平时慢</span>}
      <Button size="sm" variant="ghost" onClick={onCancel} className="ml-auto">取消</Button>
    </div>
  )
}

export function UndoToast({
  label, onUndo,
}: {
  label: string
  onUndo: () => void
}) {
  return (
    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 px-3 py-2 rounded-overlay border border-ag-line2 bg-ag-bg3">
      <span className="text-caption text-ag-ink2">{label}</span>
      <button onClick={onUndo} className="ag-focus-ring text-caption text-ag-cinnabar hover:underline">撤销</button>
    </div>
  )
}

export function MergePreview({
  targetName, pageEnd,
}: {
  targetName: string
  pageEnd: number | null
}) {
  return (
    <div className="ag-quote text-caption text-ag-ink2">
      检测到同名同类型已确认节点「{targetName}」，将自动合并
      {pageEnd != null ? `，页码范围扩展至第 ${pageEnd} 页` : ''}。
    </div>
  )
}

export function RelationNote({ dropped }: { dropped: number }) {
  if (!dropped) return null
  return (
    <div className="text-caption text-ag-statusOcr">
      {dropped} 条关系未匹配到已确认节点，本次未写入（先确认目标节点后重跑可补回）
    </div>
  )
}

export function ConfirmedSummary({
  nodes, open, onToggle,
}: {
  nodes: ConfirmedNode[]
  open: boolean
  onToggle: () => void
}) {
  return (
    <div className="shrink-0 border-t border-ag-line1 bg-ag-bg1 flex flex-col" style={{ maxHeight: open ? '28%' : 'auto' }}>
      <button
        onClick={onToggle}
        className="ag-focus-ring flex items-center gap-2 px-3 py-2 text-caption text-ag-ink3 hover:text-ag-ink1"
        aria-expanded={open}
      >
        <span aria-hidden="true">{open ? '▾' : '▸'}</span>
        <span>已确认 ({nodes.length})</span>
      </button>
      {open && (
        <div className="flex-1 overflow-auto border-t border-ag-line1">
          {nodes.length === 0 ? (
            <div className="p-3"><EmptyState>本书还没有人工确认的节点</EmptyState></div>
          ) : (
            nodes.map((n) => (
              <div key={n.id} className="h-8 px-3 flex items-center gap-2 border-b border-ag-line1">
                <EntityBadge type={n.entity_type} showLabel={false} />
                <span className="text-caption text-ag-ink1 flex-1 truncate">{n.name}</span>
                <span className="ag-mono text-micro text-ag-ink3">p{n.page_start}-{n.page_end}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
