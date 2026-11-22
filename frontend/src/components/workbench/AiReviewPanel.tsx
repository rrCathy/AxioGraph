import { useCallback, useEffect, useState } from 'react'
import Button from '../ui/Button'
import EmptyState from '../ui/EmptyState'
import { EntityBadge } from '../ui/Badge'
import * as api from '../../services/api'
import type { AiReviewEdge, AiReviewNode, AiReviewQueue } from '../../types'
import { useI18n } from '../../i18n/useI18n'

/**
 * AI auto-flow review queue: every node/edge the AI wrote on "已读" pages is
 * listed here until a human ticks it. ✓ confirms (optionally with edits first);
 * ✗ reworks just that item with the reader's note — three consecutive ✗ drop
 * the item and delete it.
 */
export default function AiReviewPanel({
  bookId, refreshKey, onChanged,
}: {
  bookId: string
  refreshKey: number
  onChanged: () => void
}) {
  const { t } = useI18n()
  const [queue, setQueue] = useState<AiReviewQueue>({ nodes: [], edges: [] })
  const [loading, setLoading] = useState(false)
  const [noteFor, setNoteFor] = useState<string | null>(null)
  const [noteDraft, setNoteDraft] = useState('')
  const [editFor, setEditFor] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editContent, setEditContent] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    if (!bookId) { setQueue({ nodes: [], edges: [] }); return }
    setLoading(true)
    try { setQueue(await api.getAiReviewQueue(bookId)) }
    finally { setLoading(false) }
  }, [bookId])

  useEffect(() => { void load() }, [load, refreshKey])

  const actNode = async (id: string, accept: boolean, edits?: { name?: string; content?: string }) => {
    setBusyId(id)
    try {
      const r = await api.aiReviewNode(id, {
        accept, note: accept ? undefined : noteDraft.trim(),
        edits: accept ? edits : undefined,
      })
      setMsg(r.action === 'confirmed' ? t('ai.doneConfirm')
        : r.action === 'dropped' ? t('ai.doneDrop')
        : t('ai.doneRework') + (r.attempts ? ` (${r.attempts}/3)` : ''))
      setNoteFor(null); setNoteDraft(''); setEditFor(null)
      await load()
      onChanged()
    } catch (e) {
      setMsg(String(e).slice(0, 120))
    } finally { setBusyId(null) }
  }

  const actEdge = async (id: number, accept: boolean) => {
    setBusyId(`e${id}`)
    try {
      const r = await api.aiReviewEdge(id, {
        accept, note: accept ? undefined : noteDraft.trim(),
      })
      setMsg(r.action === 'confirmed' ? t('ai.doneConfirm')
        : r.action === 'dropped' ? t('ai.doneDrop')
        : t('ai.doneRework') + (r.attempts ? ` (${r.attempts}/3)` : ''))
      setNoteFor(null); setNoteDraft('')
      await load()
      onChanged()
    } catch (e) {
      setMsg(String(e).slice(0, 120))
    } finally { setBusyId(null) }
  }

  const relLabel = (rt: string) => {
    const map: Record<string, string> = {
      DEPENDS_ON: '依赖于', GENERALIZES: '推广', PROVES: '证明',
      BUILDS_ON: '基于', EXAMPLE_OF: '示例',
    }
    return map[rt] ?? rt
  }

  const total = queue.nodes.length + queue.edges.length

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="shrink-0 px-3 py-1.5 border-b border-ag-line1 flex items-center gap-2">
        <span className="text-caption text-ag-ink1 font-medium">{t('ai.title')}</span>
        <span className="ag-mono text-micro text-ag-cinnabar">
          {t('ai.count').replace('{n}', String(queue.nodes.length)).replace('{m}', String(queue.edges.length))}
        </span>
        {loading && <span className="text-micro text-ag-ink3">{t('ai.loading')}</span>}
        {msg && <span className="text-micro text-ag-ink3 truncate flex-1">{msg}</span>}
      </div>

      <div className="flex-1 overflow-auto">
        {total === 0 && !loading ? (
          <div className="p-3"><EmptyState>{t('ai.empty')}</EmptyState></div>
        ) : (
          <div className="flex flex-col gap-2 p-2.5">
            {queue.nodes.map((n) => (
              <NodeRow
                key={n.id} node={n}
                busy={busyId === n.id}
                noting={noteFor === n.id}
                editing={editFor === n.id}
                noteDraft={noteDraft}
                editName={editName} editContent={editContent}
                onNoteDraft={setNoteDraft}
                onEditName={setEditName} onEditContent={setEditContent}
                onOpenNote={() => { setNoteFor(n.id); setNoteDraft(''); setEditFor(null) }}
                onOpenEdit={() => {
                  setEditFor(n.id); setNoteFor(null)
                  setEditName(n.name); setEditContent(n.content)
                }}
                onCloseOverlays={() => { setNoteFor(null); setEditFor(null) }}
                onAccept={(edits) => void actNode(n.id, true, edits)}
                onReject={() => void actNode(n.id, false)}
                relLabel={relLabel}
                t={t}
              />
            ))}
            {queue.edges.map((e) => (
              <EdgeRow
                key={`e${e.id}`} edge={e}
                busy={busyId === `e${e.id}`}
                noting={noteFor === `e${e.id}`}
                noteDraft={noteDraft}
                onNoteDraft={setNoteDraft}
                onOpenNote={() => { setNoteFor(`e${e.id}`); setNoteDraft('') }}
                onCloseNote={() => setNoteFor(null)}
                onAccept={() => void actEdge(e.id, true)}
                onReject={() => void actEdge(e.id, false)}
                relLabel={relLabel}
                t={t}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function NodeRow({
  node, busy, noting, editing, noteDraft, editName, editContent,
  onNoteDraft, onEditName, onEditContent, onOpenNote, onOpenEdit,
  onCloseOverlays, onAccept, onReject, relLabel: _relLabel, t,
}: {
  node: AiReviewNode
  busy: boolean
  noting: boolean
  editing: boolean
  noteDraft: string
  editName: string
  editContent: string
  onNoteDraft: (s: string) => void
  onEditName: (s: string) => void
  onEditContent: (s: string) => void
  onOpenNote: () => void
  onOpenEdit: () => void
  onCloseOverlays: () => void
  onAccept: (edits?: { name?: string; content?: string }) => void
  onReject: () => void
  relLabel: (rt: string) => string
  t: (k: string) => string
}) {
  return (
    <div className="rounded-card border border-ag-line2 bg-ag-bg3 p-2.5">
      <div className="flex items-center gap-2">
        <EntityBadge type={node.entity_type} />
        <span className="text-caption text-ag-ink1 font-medium flex-1 truncate">{node.name}</span>
        <span className="ag-mono text-micro text-ag-ink3">
          p{node.page_start}-{node.page_end}
          {node.ai_attempts > 0 && (
            <span className="text-ag-statusOcr ml-1">
              {t('ai.strikes').replace('{n}', String(node.ai_attempts))}
            </span>
          )}
        </span>
      </div>
      {node.source_quote && (
        <p className="ag-quote mt-1.5 text-micro text-ag-ink3 line-clamp-2">“{node.source_quote}”</p>
      )}
      <details className="mt-1">
        <summary className="text-micro text-ag-ink3 cursor-pointer">{t('ai.showContent')}</summary>
        <pre className="mt-1 text-micro whitespace-pre-wrap break-words bg-ag-bg2 p-1.5 rounded-btn max-h-32 overflow-auto">{node.content}</pre>
      </details>

      <div className="mt-2 flex gap-1.5 flex-wrap">
        <Button size="sm" variant="primary" loading={busy} onClick={() => onAccept(editing ? { name: editName, content: editContent } : undefined)}>
          {editing ? t('ai.acceptEdit') : t('ai.accept')}
        </Button>
        <Button size="sm" loading={busy} onClick={onOpenNote}>{t('ai.reject')}</Button>
        <Button size="sm" variant="ghost" onClick={editing ? onCloseOverlays : onOpenEdit}>
          {editing ? t('ai.cancel') : t('ai.edit')}
        </Button>
      </div>

      {editing && (
        <div className="mt-2 flex flex-col gap-1.5">
          <input
            value={editName}
            onChange={(e) => onEditName(e.target.value)}
            className="ag-focus-ring text-caption bg-ag-bg2 border border-ag-line2 rounded-btn px-2 py-1"
            aria-label={t('ai.name')}
          />
          <textarea
            value={editContent}
            onChange={(e) => onEditContent(e.target.value)}
            rows={4}
            className="ag-focus-ring w-full text-micro bg-ag-bg2 border border-ag-line2 rounded-btn px-2 py-1 whitespace-pre-wrap"
            aria-label={t('ai.content')}
          />
        </div>
      )}

      {noting && (
        <div className="mt-2 flex flex-col gap-1.5">
          <textarea
            value={noteDraft}
            onChange={(e) => onNoteDraft(e.target.value)}
            rows={2}
            placeholder={t('ai.notePlaceholder')}
            className="ag-focus-ring w-full text-caption bg-ag-bg2 border border-ag-line2 rounded-btn px-2 py-1"
            aria-label={t('ai.note')}
          />
          <div className="flex gap-1.5">
            <Button size="sm" variant="danger" loading={busy} onClick={onReject}>{t('ai.confirmReject')}</Button>
            <Button size="sm" variant="ghost" onClick={onCloseOverlays}>{t('ai.cancel')}</Button>
          </div>
        </div>
      )}
    </div>
  )
}

function EdgeRow({
  edge, busy, noting, noteDraft, onNoteDraft, onOpenNote, onCloseNote,
  onAccept, onReject, relLabel, t,
}: {
  edge: AiReviewEdge
  busy: boolean
  noting: boolean
  noteDraft: string
  onNoteDraft: (s: string) => void
  onOpenNote: () => void
  onCloseNote: () => void
  onAccept: () => void
  onReject: () => void
  relLabel: (rt: string) => string
  t: (k: string) => string
}) {
  return (
    <div className="rounded-card border border-ag-line2 bg-ag-bg3 p-2.5">
      <div className="flex items-center gap-1.5 text-caption text-ag-ink2">
        <span className="truncate max-w-[38%]">{edge.source_name}</span>
        <span className="ag-mono text-micro text-ag-cinnabar shrink-0">
          → {relLabel(edge.relation_type)} →
        </span>
        <span className="truncate max-w-[38%]">{edge.target_name}</span>
        {edge.ai_attempts > 0 && (
          <span className="ag-mono text-micro text-ag-statusOcr shrink-0">
            {t('ai.strikes').replace('{n}', String(edge.ai_attempts))}
          </span>
        )}
      </div>
      {edge.description && (
        <p className="text-micro text-ag-ink3 mt-1 truncate">{edge.description}</p>
      )}
      <div className="mt-2 flex gap-1.5">
        <Button size="sm" variant="primary" loading={busy} onClick={onAccept}>{t('ai.accept')}</Button>
        <Button size="sm" loading={busy} onClick={onOpenNote}>{t('ai.reject')}</Button>
      </div>
      {noting && (
        <div className="mt-2 flex flex-col gap-1.5">
          <textarea
            value={noteDraft}
            onChange={(e) => onNoteDraft(e.target.value)}
            rows={2}
            placeholder={t('ai.notePlaceholder')}
            className="ag-focus-ring w-full text-caption bg-ag-bg2 border border-ag-line2 rounded-btn px-2 py-1"
            aria-label={t('ai.note')}
          />
          <div className="flex gap-1.5">
            <Button size="sm" variant="danger" loading={busy} onClick={onReject}>{t('ai.confirmReject')}</Button>
            <Button size="sm" variant="ghost" onClick={onCloseNote}>{t('ai.cancel')}</Button>
          </div>
        </div>
      )}
    </div>
  )
}
