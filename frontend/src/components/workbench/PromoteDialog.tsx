import { useEffect, useMemo, useState } from 'react'
import Button from '../ui/Button'
import * as api from '../../services/api'
import type { RelationInput, RelationTarget, SuggestedRelation } from '../../types'
import { useI18n } from '../../i18n/useI18n'

/** Entity types offered when promoting text/environments into the graph. */
export const PROMOTE_TYPES: Array<[string, string, string]> = [
  ['DEFINITION', '定义', 'Def'], ['THEOREM', '定理', 'Thm'],
  ['LEMMA', '引理', 'Lem'], ['PROPOSITION', '命题', 'Prop'],
  ['COROLLARY', '推论', 'Cor'], ['AXIOM', '公理', 'Ax'],
  ['EXAMPLE', '例', 'Ex'], ['REMARK', '注记', 'Rmk'],
  ['CONJECTURE', '猜想', 'Cj'], ['CLAIM', '断言', 'Claim'],
  ['FACT', '事实', 'Fact'], ['ASSUMPTION', '假设', 'Asm'],
  ['PRINCIPLE', '原理', 'Pr'], ['NOTATION', '记号', 'Not'],
  ['CONCEPT', '概念', 'Con'], ['PROOF', '证明', 'Proof'],
]

export const RELATION_TYPES: Array<[string, string]> = [
  ['DEPENDS_ON', '依赖于'], ['GENERALIZES', '推广'],
  ['PROVES', '证明'], ['BUILDS_ON', '基于'], ['EXAMPLE_OF', '示例'],
]

export interface PromoteInit {
  entityType: string
  name: string
  content: string
  quote?: string
  pageStart?: number | null
  pageEnd?: number | null
}

interface Props {
  open: boolean
  bookId: string
  init: PromoteInit | null
  sourceLabel: string
  onClose: () => void
  onDone: (result: { node_id: string; action: string; undo_token: string; name: string }) => void
}

/**
 * Edit-then-promote dialog shared by environment rows and text selections.
 * Editing happens HERE (name/type/content/quote); the confirm call writes the
 * node + its relations atomically. Relations come in two flavours: manual
 * (pick a confirmed node) and AI-suggested (tick to accept). AI never writes.
 */
export default function PromoteDialog({
  open, bookId, init, sourceLabel, onClose, onDone,
}: Props) {
  const { t } = useI18n()
  const [entityType, setEntityType] = useState('DEFINITION')
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [quote, setQuote] = useState('')
  const [relations, setRelations] = useState<RelationInput[]>([])
  const [targets, setTargets] = useState<RelationTarget[]>([])
  const [pickTarget, setPickTarget] = useState('')
  const [pickType, setPickType] = useState('DEPENDS_ON')
  const [suggestions, setSuggestions] = useState<SuggestedRelation[]>([])
  const [accepted, setAccepted] = useState<Set<string>>(new Set())
  const [suggesting, setSuggesting] = useState(false)
  const [suggestFailed, setSuggestFailed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || !init) return
    setEntityType(init.entityType || 'DEFINITION')
    setName(init.name || '')
    setContent(init.content || '')
    setQuote(init.quote || '')
    setRelations([])
    setSuggestions([])
    setAccepted(new Set())
    setSuggestFailed(false)
    setError('')
    void api.listRelationTargets(bookId).then(setTargets).catch(() => setTargets([]))
  }, [open, init, bookId])

  const typeLabel = (tp: string) =>
    PROMOTE_TYPES.find(([k]) => k === tp)?.[1] ?? tp
  const relLabel = (rt: string) =>
    RELATION_TYPES.find(([k]) => k === rt)?.[1] ?? rt

  const addRelation = () => {
    if (!pickTarget) return
    const target = targets.find((x) => x.id === pickTarget)
    setRelations((prev) => [...prev, {
      target_id: pickTarget,
      relation_type: pickType,
      description: target ? `→ ${target.name}` : '',
    }])
    setPickTarget('')
  }

  const removeRelation = (i: number) =>
    setRelations((prev) => prev.filter((_, j) => j !== i))

  const runSuggest = async () => {
    setSuggesting(true)
    setSuggestFailed(false)
    try {
      const r = await api.suggestRelations(bookId, {
        name, entity_type: entityType, content, limit: 8,
      })
      setSuggestions(r.relations)
      setAccepted(new Set())
      if (r.degraded || (r.relations.length === 0)) setSuggestFailed(r.degraded ?? false)
    } catch {
      setSuggestFailed(true)
    } finally {
      setSuggesting(false)
    }
  }

  const toggleAccept = (key: string) => {
    setAccepted((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const acceptSuggestions = () => {
    const chosen = suggestions
      .filter((s) => accepted.has(s.target_id + s.relation_type))
      .map((s) => ({
        target_id: s.target_id,
        relation_type: s.relation_type,
        description: s.note || `→ ${s.target_name}`,
      }))
    setRelations((prev) => {
      const seen = new Set(prev.map((r) => r.target_id + r.relation_type))
      return [...prev, ...chosen.filter((c) => !seen.has(c.target_id + c.relation_type))]
    })
    setSuggestions([])
    setAccepted(new Set())
  }

  const submit = async () => {
    if (!name.trim()) { setError('名称不能为空'); return }
    setSaving(true)
    setError('')
    try {
      const r = await api.promoteNode(bookId, {
        entity_type: entityType,
        name: name.trim(),
        content,
        quote: quote || null,
        page_start: init?.pageStart ?? null,
        page_end: init?.pageEnd ?? null,
        relations,
      })
      onDone({ node_id: r.node_id, action: r.action, undo_token: r.undo_token, name: name.trim() })
    } catch (e) {
      setError(String(e).slice(0, 160))
    } finally {
      setSaving(false)
    }
  }

  const remaining = useMemo(
    () => targets.filter((x) => !relations.some((r) => r.target_id === x.id)),
    [targets, relations],
  )

  if (!open || !init) return null

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div
        role="dialog" aria-modal="true" aria-label="提升为图谱节点"
        className="w-[min(640px,94vw)] max-h-[88vh] overflow-auto rounded-overlay border border-ag-line2 bg-ag-bg3 p-5"
      >
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-h2 font-medium text-ag-ink1">{t('promote.title')}</h2>
          <span className="text-micro text-ag-ink3 ag-mono">{sourceLabel}</span>
          <button
            onClick={onClose}
            className="ag-focus-ring ml-auto text-caption text-ag-ink3 hover:text-ag-ink1"
            aria-label={t('promote.close')}
          >✕</button>
        </div>

        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <label className="text-caption text-ag-ink3 w-14 shrink-0">{t('promote.type')}</label>
            <select
              value={entityType}
              onChange={(e) => setEntityType(e.target.value)}
              className="ag-focus-ring text-caption bg-ag-bg2 border border-ag-line2 rounded-btn px-2 py-1"
              aria-label={t('promote.type')}
            >
              {PROMOTE_TYPES.map(([k, zh]) => <option key={k} value={k}>{zh} ({k})</option>)}
            </select>
            <label className="text-caption text-ag-ink3 w-14 shrink-0">{t('promote.name')}</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="ag-focus-ring flex-1 text-caption bg-ag-bg2 border border-ag-line2 rounded-btn px-2 py-1"
              aria-label={t('promote.name')}
            />
          </div>

          <div>
            <label className="text-caption text-ag-ink3 block mb-1">{t('promote.content')}</label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={6}
              className="ag-focus-ring w-full text-caption bg-ag-bg2 border border-ag-line2 rounded-btn px-2 py-1.5 whitespace-pre-wrap"
              aria-label={t('promote.content')}
            />
          </div>

          <div>
            <label className="text-caption text-ag-ink3 block mb-1">{t('promote.quote')}</label>
            <input
              value={quote}
              onChange={(e) => setQuote(e.target.value)}
              className="ag-focus-ring w-full text-caption bg-ag-bg2 border border-ag-line2 rounded-btn px-2 py-1"
              aria-label={t('promote.quote')}
            />
          </div>

          {/* Relations */}
          <div className="rounded-card border border-ag-line2 bg-ag-bg2 p-3">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-caption text-ag-ink1 font-medium">{t('promote.relations')}</span>
              <Button size="sm" variant="ghost" loading={suggesting} onClick={() => void runSuggest()}>
                {t('promote.suggest')}
              </Button>
            </div>

            {suggestFailed && (
              <div className="text-micro text-ag-statusOcr mb-2">{t('promote.suggestFailed')}</div>
            )}

            {suggestions.length > 0 && (
              <div className="mb-2 flex flex-col gap-1">
                {suggestions.map((s) => {
                  const key = s.target_id + s.relation_type
                  return (
                    <label key={key} className="flex items-start gap-2 text-caption text-ag-ink2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={accepted.has(key)}
                        onChange={() => toggleAccept(key)}
                        className="mt-0.5"
                      />
                      <span className="flex-1 min-w-0">
                        <span className="ag-mono text-micro text-ag-cinnabar mr-1">{relLabel(s.relation_type)}</span>
                        {s.target_name}
                        {s.note && <span className="text-micro text-ag-ink3"> — {s.note}</span>}
                      </span>
                    </label>
                  )
                })}
                <Button size="sm" variant="primary" disabled={accepted.size === 0} onClick={acceptSuggestions}>
                  {t('promote.acceptChecked').replace('{n}', String(accepted.size))}
                </Button>
              </div>
            )}

            {relations.length > 0 && (
              <div className="flex flex-col gap-1 mb-2">
                {relations.map((r, i) => {
                  const target = targets.find((x) => x.id === r.target_id)
                  return (
                    <div key={i} className="flex items-center gap-2 text-caption text-ag-ink2">
                      <span className="ag-mono text-micro text-ag-cinnabar">{relLabel(r.relation_type)}</span>
                      <span className="flex-1 truncate">{target?.name ?? r.target_id.slice(0, 8)}</span>
                      <button
                        onClick={() => removeRelation(i)}
                        className="ag-focus-ring text-micro text-ag-ink3 hover:text-ag-ink1"
                        aria-label={t('promote.relRemove')}
                      >✕</button>
                    </div>
                  )
                })}
              </div>
            )}

            <div className="flex items-center gap-1.5 flex-wrap">
              <select
                value={pickTarget}
                onChange={(e) => setPickTarget(e.target.value)}
                className="ag-focus-ring text-caption bg-ag-bg3 border border-ag-line2 rounded-btn px-2 py-1 max-w-[220px] truncate"
                aria-label={t('promote.relTarget')}
              >
                <option value="">{t('promote.relTarget')}</option>
                {remaining.map((x) => (
                  <option key={x.id} value={x.id}>{x.name}</option>
                ))}
              </select>
              <select
                value={pickType}
                onChange={(e) => setPickType(e.target.value)}
                className="ag-focus-ring text-caption bg-ag-bg3 border border-ag-line2 rounded-btn px-2 py-1"
                aria-label={t('promote.relType')}
              >
                {RELATION_TYPES.map(([k, zh]) => <option key={k} value={k}>{zh}</option>)}
              </select>
              <Button size="sm" disabled={!pickTarget} onClick={addRelation}>
                {t('promote.relAdd')}
              </Button>
            </div>
            {targets.length === 0 && (
              <div className="mt-2 text-micro text-ag-ink3">{t('promote.noTargets')}</div>
            )}
          </div>
        </div>

        {error && <div className="mt-3 text-caption text-ag-statusOcr">{error}</div>}

        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="ag-focus-ring h-8 px-3 rounded-btn text-body text-ag-ink2 border border-ag-line2 hover:bg-ag-bg4"
          >
            {t('promote.cancel')}
          </button>
          <Button variant="primary" loading={saving} onClick={() => void submit()}>
            {t('promote.submit')}
          </Button>
        </div>
      </div>
    </div>
  )
}
