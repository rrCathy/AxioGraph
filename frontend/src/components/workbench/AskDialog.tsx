import { useCallback, useEffect, useState } from 'react'
import Button from '../ui/Button'
import * as api from '../../services/api'
import type { AskSectionResult, QaRecord } from '../../types'
import { useI18n } from '../../i18n/useI18n'

interface Props {
  open: boolean
  bookId: string
  pageNo: number
  selection: string
  onClose: () => void
}

/**
 * Selection Q&A: the question carries the selected text; the backend fills in
 * the current section (TOC entry covering this page) as context automatically.
 * Answers are saved to the page (qa_records) — history only, never a node.
 */
export default function AskDialog({ open, bookId, pageNo, selection, onClose }: Props) {
  const { t } = useI18n()
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [result, setResult] = useState<AskSectionResult | null>(null)
  const [error, setError] = useState('')
  const [history, setHistory] = useState<QaRecord[]>([])
  const [showHistory, setShowHistory] = useState(false)

  const loadHistory = useCallback(async () => {
    if (!open || !bookId) return
    try {
      setHistory(await api.listPageQa(bookId, pageNo))
    } catch { setHistory([]) }
  }, [open, bookId, pageNo])

  useEffect(() => {
    if (!open) return
    setResult(null)
    setError('')
    setQuestion('')
    void loadHistory()
  }, [open, loadHistory])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const ask = async () => {
    if (!question.trim() || asking) return
    setAsking(true)
    setError('')
    setResult(null)
    try {
      const r = await api.askSection(bookId, {
        question: question.trim(),
        selection,
        page_no: pageNo,
      })
      setResult(r)
      void loadHistory()
    } catch (e) {
      setError(String(e).slice(0, 200))
    } finally {
      setAsking(false)
    }
  }

  const removeRecord = async (id: string) => {
    await api.deleteQa(id).catch(() => {})
    void loadHistory()
  }

  if (!open) return null

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div
        role="dialog" aria-modal="true" aria-label={t('ask.title')}
        className="w-[min(680px,94vw)] max-h-[88vh] overflow-auto rounded-overlay border border-ag-line2 bg-ag-bg3 p-5"
      >
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-h2 font-medium text-ag-ink1">{t('ask.title')}</h2>
          <span className="ag-mono text-micro text-ag-ink3">p{pageNo}</span>
          <button
            onClick={onClose}
            className="ag-focus-ring ml-auto text-caption text-ag-ink3 hover:text-ag-ink1"
            aria-label={t('promote.close')}
          >✕</button>
        </div>

        {selection && (
          <div className="mb-3">
            <div className="text-micro text-ag-ink3 mb-1">{t('ask.selection')}</div>
            <div className="ag-quote text-caption text-ag-ink2 max-h-24 overflow-auto rounded-btn bg-ag-bg2 p-2">
              “{selection.slice(0, 400)}{selection.length > 400 ? '…' : ''}”
            </div>
          </div>
        )}

        <div className="flex flex-col gap-2">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={3}
            placeholder={t('ask.placeholder')}
            className="ag-focus-ring w-full text-caption bg-ag-bg2 border border-ag-line2 rounded-btn px-2 py-1.5"
            aria-label={t('ask.question')}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void ask() }
            }}
          />
          <div className="flex items-center gap-2">
            <Button variant="primary" loading={asking} disabled={!question.trim()} onClick={() => void ask()}>
              {t('ask.submit')}
            </Button>
            <span className="text-micro text-ag-ink3">{t('ask.hint')}</span>
          </div>
        </div>

        {error && <div className="mt-3 text-caption text-ag-statusOcr">{error}</div>}

        {result && (
          <div className="mt-4">
            <div className="flex items-center gap-2 mb-1.5">
              <span className="text-caption text-ag-ink1 font-medium">{t('ask.answer')}</span>
              <span className="ag-mono text-micro text-ag-cinnabar">
                {t('ask.context')
                  .replace('{s}', result.section.title || `p${result.section.start}`)
                  .replace('{a}', String(result.section.start))
                  .replace('{b}', String(result.section.end))
                  .replace('{n}', (result.section.chars / 1000).toFixed(1))}
              </span>
            </div>
            <div className="text-body text-ag-ink2 leading-relaxed whitespace-pre-wrap rounded-btn bg-ag-bg2 p-3 max-h-[40vh] overflow-auto">
              {result.answer}
            </div>
          </div>
        )}

        <div className="mt-4 border-t border-ag-line1 pt-2">
          <button
            onClick={() => setShowHistory((v) => !v)}
            className="ag-focus-ring flex items-center gap-2 text-caption text-ag-ink3 hover:text-ag-ink1"
            aria-expanded={showHistory}
          >
            <span aria-hidden="true">{showHistory ? '▾' : '▸'}</span>
            <span>{t('ask.history').replace('{n}', String(history.length))}</span>
          </button>
          {showHistory && (
            <div className="mt-2 flex flex-col gap-2">
              {history.length === 0 ? (
                <div className="text-micro text-ag-ink3">{t('ask.noHistory')}</div>
              ) : history.map((h) => (
                <div key={h.id} className="rounded-btn border border-ag-line1 bg-ag-bg2 p-2">
                  <div className="flex items-start gap-2">
                    <span className="flex-1 text-caption text-ag-ink1">{h.question}</span>
                    <button
                      onClick={() => void removeRecord(h.id)}
                      className="ag-focus-ring text-micro text-ag-ink3 hover:text-ag-ink1"
                      aria-label={t('ask.delete')}
                    >✕</button>
                  </div>
                  {h.section_title && (
                    <div className="ag-mono text-micro text-ag-ink3 mt-0.5">{h.section_title}</div>
                  )}
                  {h.answer && (
                    <div className="text-caption text-ag-ink2 mt-1 whitespace-pre-wrap max-h-28 overflow-auto">
                      {h.answer}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
