import { useState, useEffect, useMemo } from 'react'
import { getNodeDetail, updateNode, deleteNode, getGraph, translateText } from '../services/api'
import { useAppStore } from '../stores/appStore'
import type { NodeDetail as INodeDetail } from '../types'
import MathContent from './MathContent'
import { useI18n } from '../i18n/useI18n'
import Button from './ui/Button'
import ConfirmDialog from './ui/ConfirmDialog'
import { EntityBadge } from './ui/Badge'
import { entityMetaOf } from '../theme/entityMeta'

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

const SECTION_LABELS: Record<string, string> = {
  statement: '陈述', proof: '证明', definition: '定义', explanation: '解释',
  problem: '问题', solution: '解答', note: '注记',
}
const SECTION_LABELS_EN: Record<string, string> = {
  statement: 'Statement', proof: 'Proof', definition: 'Definition', explanation: 'Explanation',
  problem: 'Problem', solution: 'Solution', note: 'Note',
}

export default function NodeDetail({ nodeId }: { nodeId: string }) {
  const [node, setNode] = useState<INodeDetail | null>(null)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [translating, setTranslating] = useState(false)
  const [translatedText, setTranslatedText] = useState<string | null>(null)
  const [showOriginal, setShowOriginal] = useState(true)
  const [confirmDelete, setConfirmDelete] = useState(false)
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
    setConfirmDelete(false)
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

  if (error) return <div className="p-4 text-caption text-ag-danger">{error}</div>
  if (!node) return <div className="p-4 text-caption text-ag-ink3">{t('node.loading')}</div>

  const meta = entityMetaOf(node.entity_type)

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <EntityBadge type={node.entity_type} />
        <div className="flex gap-1">
          <Button size="sm" variant="ghost" onClick={() => setEditing(!editing)}>
            {editing ? t('node.cancel') : t('node.edit')}
          </Button>
          <Button size="sm" variant="danger" onClick={() => setConfirmDelete(true)}>
            {t('node.delete')}
          </Button>
        </div>
      </div>

      {editing ? (
        <div className="flex flex-col gap-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="ag-focus-ring w-full bg-ag-bg2 rounded-btn px-3 py-1.5 text-body border border-ag-line2 text-ag-ink1"
          />
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={8}
            className="ag-focus-ring w-full bg-ag-bg2 rounded-btn px-3 py-1.5 text-caption ag-mono border border-ag-line2 text-ag-ink1"
          />
          <Button variant="primary" onClick={() => void handleSave()}>{t('node.save')}</Button>
        </div>
      ) : (
        <>
          <h3 className="text-h2 font-medium mb-1 text-ag-ink1 leading-tight">
            <MathContent text={node.name} />
          </h3>
          {node.chapter && (
            <p className="ag-mono text-caption text-ag-ink3 mb-4">{t('node.chapter')}{node.chapter}</p>
          )}

          {structured ? (
            <div className="flex flex-col gap-3">
              {Object.entries(sectionLabels).map(([key, label]) => {
                const value = (structured as any)[key]
                if (!value) return null
                const isProof = key === 'proof'
                return (
                  <details key={key} open={!isProof} className="group">
                    <summary className={`cursor-pointer text-caption font-medium tracking-wide mb-1.5 select-none
                      ${isProof ? 'text-ag-entityThe' : 'text-ag-entityDef'}`}
                    >
                      {label}
                    </summary>
                    <div className={`text-body leading-relaxed rounded-card p-3 mt-1 border
                      ${isProof ? 'bg-ag-entityTheBg border-ag-line1' : 'bg-ag-bg3 border-ag-line1'}`}>
                      <MathContent text={value} />
                    </div>
                  </details>
                )
              })}
            </div>
          ) : (
            content ? (
              <div>
                <div className="text-body text-ag-ink2 leading-relaxed bg-ag-bg3 rounded-card p-3 border border-ag-line1">
                  <MathContent text={showOriginal ? content : (translatedText || content)} />
                </div>

                {!/[\u4e00-\u9fff]/.test(content.slice(0, 200)) && (
                  <div className="mt-2 flex flex-col gap-2">
                    {!translatedText ? (
                      <Button size="sm" onClick={handleTranslate} loading={translating}>
                        {translating ? t('node.translating') : t('node.translate')}
                      </Button>
                    ) : (
                      <div>
                        <div className="flex items-center gap-2 mb-1.5">
                          <span className="ag-mono text-micro text-ag-ink3">
                            {showOriginal ? t('node.showOriginal') : '中文'}
                          </span>
                          <button
                            onClick={() => setShowOriginal(!showOriginal)}
                            className="ag-focus-ring text-caption text-ag-cinnabar hover:underline"
                          >
                            {showOriginal ? t('node.translate') : t('node.hideOriginal')}
                          </button>
                        </div>
                        {!showOriginal && translatedText && (
                          <div className="text-body text-ag-ink2 leading-relaxed bg-ag-quoteBg rounded-card p-3 border border-ag-line1">
                            <MathContent text={translatedText} />
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-body text-ag-ink3 italic bg-ag-bg3 rounded-card p-3 border border-ag-line1">
                {t('node.noContent')}
              </div>
            )
          )}
        </>
      )}

      <ConfirmDialog
        open={confirmDelete}
        title={t('node.delete')}
        description={`删除「${node.name}」及其全部关系。此操作不可撤销。`}
        confirmLabel={t('node.delete')}
        destructive
        onConfirm={() => void handleDelete()}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  )
}
