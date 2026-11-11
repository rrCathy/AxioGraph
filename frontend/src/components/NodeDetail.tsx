import { useState, useEffect, useMemo } from 'react'
import { getNodeDetail, updateNode, deleteNode, getGraph, translateText } from '../services/api'
import { useAppStore } from '../stores/appStore'
import type { NodeDetail as INodeDetail } from '../types'
import MathContent from './MathContent'
import { useI18n } from '../i18n/useI18n'

// ─── Structured content type ────────────────────────────
interface StructuredContent {
  statement?: string
  proof?: string
  definition?: string
  explanation?: string
  problem?: string
  solution?: string
  note?: string
}

function parseContent(raw: string): StructuredContent | null {
  if (!raw || !raw.trim().startsWith('{')) return null
  try {
    const obj = JSON.parse(raw)
    if (typeof obj === 'object' && obj !== null && !Array.isArray(obj)) {
      return obj as StructuredContent
    }
  } catch {}
  return null
}

// ─── Section label map ───────────────────────────────────
const SECTION_LABELS: Record<string, string> = {
  statement: '陈述', proof: '证明', definition: '定义', explanation: '解释',
  problem: '问题', solution: '解答', note: '注记',
}
const SECTION_LABELS_EN: Record<string, string> = {
  statement: 'Statement', proof: 'Proof', definition: 'Definition', explanation: 'Explanation',
  problem: 'Problem', solution: 'Solution', note: 'Note',
}

// ─── Main component ──────────────────────────────────────
export default function NodeDetail({ nodeId }: { nodeId: string }) {
  const [node, setNode] = useState<INodeDetail | null>(null)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [translating, setTranslating] = useState(false)
  const [translatedText, setTranslatedText] = useState<string | null>(null)
  const [showOriginal, setShowOriginal] = useState(true)
  const { selectNode, setGraphData, selectedBookId, lang } = useAppStore()
  const { t } = useI18n()

  const sectionLabels = lang === 'en' ? SECTION_LABELS_EN : SECTION_LABELS

  useEffect(() => {
    setError(null)
    setNode(null)
    getNodeDetail(nodeId)
      .then((data) => {
        if (!data || !data.id) {
          setError(`${t('node.loading')} ${nodeId.slice(0, 8)}...`)
          return
        }
        setNode(data)
        setName(data.name || '')
        setContent(data.content || '')
        setTranslatedText(null)
        setShowOriginal(true)
      })
      .catch((err) => {
        setError(`${t('node.loading')}：${err.message}`)
      })
  }, [nodeId])

  const structured = useMemo(() => parseContent(content), [content])

  const handleSave = async () => {
    await updateNode(nodeId, name, content)
    setNode((prev) => prev ? { ...prev, name, content } : null)
    setEditing(false)
    if (selectedBookId) {
      const data = await getGraph(selectedBookId)
      setGraphData(data)
    }
  }

  const handleDelete = async () => {
    if (!confirm(t('node.confirmDelete'))) return
    await deleteNode(nodeId)
    selectNode(null)
    if (selectedBookId) {
      const data = await getGraph(selectedBookId)
      setGraphData(data)
    }
  }

  const handleTranslate = async () => {
    setTranslating(true)
    setTranslatedText(null)
    try {
      const result = await translateText(content, 'zh')
      setTranslatedText(result.translated || result.text || '')
    } catch {
      setTranslatedText('Translation failed')
    } finally {
      setTranslating(false)
    }
  }

  if (error) return <div className="p-4 text-red-400 text-sm">{error}</div>
  if (!node) return <div className="p-4 text-gray-500 text-sm">{t('node.loading')}</div>

  const typeColors: Record<string, string> = {
    DEFINITION: '#4CAF50', THEOREM: '#2196F3', LEMMA: '#03A9F4',
    COROLLARY: '#00BCD4', AXIOM: '#F44336', PROOF: '#9E9E9E',
    EXAMPLE: '#FF9800', CONCEPT: '#9C27B0', PROPOSITION: '#FF7043',
  }

  return (
    <div className="p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <span
          className="px-2 py-0.5 text-xs rounded-full font-medium"
          style={{ backgroundColor: typeColors[node.entity_type] || '#666' }}
        >
          {node.entity_type}
        </span>
        <div className="flex gap-1">
          <button
            onClick={() => setEditing(!editing)}
            className="px-2 py-0.5 text-xs bg-gray-700 hover:bg-gray-600 rounded transition"
          >
            {editing ? t('node.cancel') : t('node.edit')}
          </button>
          <button
            onClick={handleDelete}
            className="px-2 py-0.5 text-xs bg-red-800 hover:bg-red-700 rounded transition"
          >
            {t('node.delete')}
          </button>
        </div>
      </div>

      {editing ? (
        <div className="space-y-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full bg-gray-800 rounded px-3 py-1.5 text-sm border border-gray-700 focus:border-blue-500 outline-none"
          />
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={8}
            className="w-full bg-gray-800 rounded px-3 py-1.5 text-sm font-mono border border-gray-700 focus:border-blue-500 outline-none"
          />
          <button
            onClick={handleSave}
            className="w-full py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm transition"
          >
            {t('node.save')}
          </button>
        </div>
      ) : (
        <>
          {/* Name */}
          <h3 className="text-lg font-semibold mb-1 text-gray-100 leading-tight">
            <MathContent text={node.name} />
          </h3>
          {node.chapter && (
            <p className="text-xs text-gray-500 mb-4">{t('node.chapter')}{node.chapter}</p>
          )}

          {/* Structured content */}
          {structured ? (
            <div className="space-y-3">
              {Object.entries(sectionLabels).map(([key, label]) => {
                const value = (structured as any)[key]
                if (!value) return null
                const isProof = key === 'proof'
                return (
                  <details key={key} open={!isProof} className="group">
                    <summary className={`cursor-pointer text-xs font-medium uppercase tracking-wide mb-1.5 select-none
                      ${isProof
                        ? 'text-purple-400 hover:text-purple-300'
                        : 'text-blue-400 hover:text-blue-300'}`}
                    >
                      {label}
                    </summary>
                    <div className={`
                      text-sm leading-relaxed rounded-lg p-3 mt-1
                      ${isProof
                        ? 'bg-purple-500/5 border border-purple-500/20'
                        : 'bg-gray-800/50 border border-gray-700/50'}
                    `}>
                      <MathContent text={value} />
                    </div>
                  </details>
                )
              })}
            </div>
          ) : (
            /* Fallback: flat string content */
            content ? (
              <div>
                <div className="text-sm text-gray-300 leading-relaxed bg-gray-800/50 rounded-lg p-3 border border-gray-700/50">
                  <MathContent text={showOriginal ? content : (translatedText || content)} />
                </div>

                {/* Translate button */}
                {!/[\u4e00-\u9fff]/.test(content.slice(0, 200)) && (
                  <div className="mt-2 space-y-2">
                    {!translatedText ? (
                      <button
                        onClick={handleTranslate}
                        disabled={translating}
                        className="w-full py-1.5 text-xs rounded-lg bg-surface-hover hover:bg-surface-overlay text-text-secondary border border-border-subtle transition-colors disabled:opacity-50"
                      >
                        {translating ? t('node.translating') : t('node.translate')}
                      </button>
                    ) : (
                      <div>
                        <div className="flex items-center gap-2 mb-1.5">
                          <span className="text-2xs text-text-dim">
                            {showOriginal ? t('node.showOriginal') : '\u4E2D\u6587'}
                          </span>
                          <button
                            onClick={() => setShowOriginal(!showOriginal)}
                            className="text-xs text-accent-blue hover:text-accent-purple transition-colors"
                          >
                            {showOriginal ? t('node.translate') : t('node.hideOriginal')}
                          </button>
                        </div>
                        {!showOriginal && translatedText && (
                          <div className="text-sm text-gray-300 leading-relaxed bg-blue-500/5 rounded-lg p-3 border border-blue-500/20">
                            <MathContent text={translatedText} />
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-sm text-gray-500 italic bg-gray-800/30 rounded-lg p-3">
                {t('node.noContent')}
              </div>
            )
          )}
        </>
      )}
    </div>
  )
}
