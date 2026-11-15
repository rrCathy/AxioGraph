import { useEffect, useMemo, useRef, useState } from 'react'
import Button from '../ui/Button'
import EmptyState from '../ui/EmptyState'
import { EntityBadge } from '../ui/Badge'
import type { ConfirmedNode, Environment, TextBlock, PageLayout } from '../../types'
import type { LongTaskState } from '../../hooks/useLongTask'
import { pageImageUrl } from '../../services/api'
import { useI18n } from '../../i18n/useI18n'

export type ZoomMode = 'fitw' | 'fitp' | 'orig'

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

const SHEET_CHROME = 30 // page-sheet padding + border, both sides

// Display order and bilingual labels for theorem-like environments.
const ENV_ORDER: Array<[Environment['kind'], string, string]> = [
  ['theorem', '定理', 'Thm'], ['lemma', '引理', 'Lem'],
  ['proposition', '命题', 'Prop'], ['corollary', '推论', 'Cor'],
  ['definition', '定义', 'Def'], ['example', '例', 'Ex'],
  ['remark', '注记', 'Rmk'], ['notation', '记号', 'Not'],
  ['convention', '约定', 'Conv'], ['problem', '问题', 'Q'],
  ['exercise', '习题', 'Exr'], ['warning', '警告', 'Warn'],
  ['proof', '证明', 'Proof'],
]

export function LayoutBar({
  layout, environments, structured, onToggle, onRelayout,
}: {
  layout?: PageLayout | null
  environments?: Environment[]
  structured: boolean
  onToggle: (v: boolean) => void
  onRelayout: () => void
}) {
  const { t, lang } = useI18n()
  if (!layout) return null
  const c = layout.counts || {}
  const counts = t('workbench.layoutCounts')
    .replace('{h}', String(c.H ?? 0))
    .replace('{t}', String(c.TABLE ?? 0))
    .replace('{p}', String(c.P ?? 0))
    .replace('{f}', String(c.FORMULA ?? 0))
    .replace('{d}', String(c.DIAGRAM ?? 0))
    .replace('{g}', String(c.FIGURE ?? 0))
  const chip = 'ag-focus-ring px-2 py-0.5 text-micro rounded-btn border transition-colors'
  const envCounts = ENV_ORDER
    .map(([kind, zh, en]) => [kind, lang === 'zh' ? zh : en,
      (environments ?? []).filter((e) => e.kind === kind).length] as const)
    .filter(([, , n]) => n > 0)
    .map(([, label, n]) => `${label} ${n}`)
    .join(' · ')

  return (
    <div className="shrink-0 flex items-center gap-2 px-3 py-1.5 border-b border-ag-line1 bg-ag-bg2 flex-wrap">
      <span className="text-caption text-ag-ink3">{t('workbench.layoutBar')}</span>
      <span className="ag-mono text-micro text-ag-ink2">{counts}</span>
      {envCounts && (
        <span className="ag-mono text-micro text-ag-cinnabar" title={t('workbench.envSummary')}>
          {envCounts}
        </span>
      )}
      <span className={`text-micro px-1.5 py-0.5 rounded-badge border ${
        layout.page_kind === 'text_layer'
          ? 'border-ag-line2 text-ag-ink3'
          : 'border-ag-statusOcr text-ag-statusOcr'}`}>
        {layout.page_kind === 'text_layer'
          ? t('workbench.layoutKindText')
          : layout.page_kind === 'mixed_ocr'
            ? t('workbench.layoutKindMixed')
            : t('workbench.layoutKindScan')}
      </span>
      {layout.text_source && (
        <span className="ag-mono text-micro text-ag-ink3">
          {t('workbench.layoutSource')}: {layout.text_source === 'rapidocr'
            ? t('workbench.layoutSourceOcr')
            : t('workbench.layoutSourceLayer')}
        </span>
      )}
      {(c.FIGURE ?? 0) > 0 && (
        <span className="text-micro text-ag-ink3">{t('workbench.layoutFigures')}</span>
      )}
      {layout.formula_total != null && layout.formula_total > 0 && (
        <span className="ag-mono text-micro text-ag-ink3">
          {t('workbench.formulaStrip')
            .replace('{r}', String(layout.formula_recognized ?? 0))
            .replace('{n}', String(layout.formula_total))}
        </span>
      )}
      <div className="ml-auto flex items-center gap-1">
        <button
          onClick={() => onToggle(true)}
          aria-pressed={structured}
          className={`${chip} ${structured ? 'border-ag-cinnabar text-ag-ink1 bg-ag-quoteBg' : 'border-transparent text-ag-ink3 hover:text-ag-ink1'}`}
        >
          {t('workbench.layoutStructured')}
        </button>
        <button
          onClick={() => onToggle(false)}
          aria-pressed={!structured}
          className={`${chip} ${!structured ? 'border-ag-cinnabar text-ag-ink1 bg-ag-quoteBg' : 'border-transparent text-ag-ink3 hover:text-ag-ink1'}`}
        >
          {t('workbench.layoutRaw')}
        </button>
        <button onClick={onRelayout} className={`${chip} border-ag-line2 text-ag-ink3 hover:text-ag-ink1`}>
          {t('workbench.layoutRelayout')}
        </button>
      </div>
      {layout.needs_vision && (
        <div className="w-full text-caption text-ag-statusOcr" role="status">
          {t('workbench.layoutNeedsVision')}
        </div>
      )}
    </div>
  )
}

/** Full-page viewer: scroll + three zoom levels + quote overlay. */
export function PageViewer({
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
  const { t } = useI18n()
  const wellRef = useRef<HTMLDivElement>(null)
  const [well, setWell] = useState({ w: 0, h: 0 })
  const [zoomMode, setZoomMode] = useState<ZoomMode>('fitw')

  useEffect(() => {
    const el = wellRef.current
    if (!el) return
    const update = () => setWell({ w: el.clientWidth, h: el.clientHeight })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const zoom = useMemo(() => {
    if (!pageWidth || pageWidth <= 0 || well.w <= 0) return 1.3
    const fitw = (well.w - SHEET_CHROME) / pageWidth
    if (zoomMode === 'fitw') return Math.max(0.5, Math.min(3.0, fitw))
    if (zoomMode === 'fitp' && pageHeight && pageHeight > 0) {
      const fitp = Math.min(fitw, (well.h - SHEET_CHROME - 28) / pageHeight)
      return Math.max(0.5, Math.min(3.0, fitp))
    }
    return 1.0
  }, [zoomMode, well, pageWidth, pageHeight])

  const imgWidth = pageWidth && pageWidth > 0 ? Math.round(pageWidth * zoom) : undefined
  const key = quote.slice(0, 12)
  const hit = quote && pageWidth && pageHeight
    ? blocks.find((b) => b.text.includes(key))
    : null

  const zoomBtn = (mode: ZoomMode, label: string) => (
    <button
      key={mode}
      onClick={() => setZoomMode(mode)}
      aria-pressed={zoomMode === mode}
      className={`ag-focus-ring px-2 py-0.5 text-caption rounded-btn border transition-colors ${
        zoomMode === mode
          ? 'border-ag-cinnabar text-ag-ink1 bg-ag-quoteBg'
          : 'border-transparent text-ag-ink3 hover:text-ag-ink1'
      }`}
    >
      {label}
    </button>
  )

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 border-b border-ag-line1 bg-ag-bg2">
        <span className="text-caption text-ag-ink3 flex-1 ag-mono" aria-live="polite">
          {Math.round(zoom * 100)}%
        </span>
        {zoomBtn('fitw', t('workbench.zoomFitWidth'))}
        {zoomBtn('fitp', t('workbench.zoomFitPage'))}
        {zoomBtn('orig', t('workbench.zoomOrig'))}
      </div>
      <div ref={wellRef} className="ag-page-well flex-1 overflow-auto">
        <div className="shrink-0 text-caption text-ag-ink3 mb-3 ag-mono">
          原页为图像，划选请在右侧「提取文本」中进行
        </div>
        <div
          className="page-sheet"
          style={zoomMode === 'fitw'
            ? undefined
            : { maxWidth: 'none', width: imgWidth ? imgWidth + SHEET_CHROME : undefined, margin: '0 auto' }}
        >
          <div className="relative">
            <img
              src={pageImageUrl(bookId, pageNo, zoom)}
              alt={`第 ${pageNo} 页原页`}
              draggable={false}
              style={imgWidth ? { width: imgWidth, height: 'auto' } : undefined}
            />
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
