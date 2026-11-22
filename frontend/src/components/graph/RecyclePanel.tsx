import { useCallback, useEffect, useState } from 'react'
import Button from '../ui/Button'
import EmptyState from '../ui/EmptyState'
import { EntityBadge } from '../ui/Badge'
import * as api from '../../services/api'
import type { RecycleBin } from '../../types'
import { useI18n } from '../../i18n/useI18n'

/**
 * Recycle bin: every soft-deleted node lives here until restored or purged.
 * Restoring brings the node back together with the edges that were
 * cascade-hidden when it was deleted.
 */
export default function RecyclePanel({
  bookId, open, onClose, onChanged,
}: {
  bookId: string
  open: boolean
  onClose: () => void
  onChanged: () => void
}) {
  const { t } = useI18n()
  const [bin, setBin] = useState<RecycleBin>({ nodes: [], edges: [] })
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (!bookId || !open) return
    setLoading(true)
    try { setBin(await api.getRecycleBin(bookId)) } finally { setLoading(false) }
  }, [bookId, open])

  useEffect(() => { void load() }, [load])

  if (!open) return null

  const restore = async (ids: string[]) => {
    setBusy(true)
    try {
      await api.recycleRestore(ids)
      setMsg(t('recycle.restored').replace('{n}', String(ids.length)))
      await load()
      onChanged()
    } finally { setBusy(false) }
  }

  const purge = async (ids: string[]) => {
    setBusy(true)
    try {
      await api.recyclePurge(ids)
      setMsg(t('recycle.purged').replace('{n}', String(ids.length)))
      await load()
    } finally { setBusy(false) }
  }

  const purgeAll = async () => {
    setBusy(true)
    try {
      await api.recyclePurgeAll(bookId)
      setMsg(t('recycle.purgeAllDone'))
      await load()
    } finally { setBusy(false) }
  }

  return (
    <div className="absolute bottom-10 right-3 z-30 w-[min(420px,90%)] max-h-[55%] flex flex-col rounded-overlay border border-ag-line2 bg-ag-bg3 shadow-overlay">
      <div className="shrink-0 flex items-center gap-2 px-3 py-2 border-b border-ag-line1">
        <span className="text-caption text-ag-ink1 font-medium">{t('recycle.title')}</span>
        <span className="ag-mono text-micro text-ag-cinnabar">
          {t('recycle.count').replace('{n}', String(bin.nodes.length))}
        </span>
        <button
          onClick={onClose}
          className="ag-focus-ring ml-auto text-caption text-ag-ink3 hover:text-ag-ink1"
          aria-label={t('recycle.close')}
        >✕</button>
      </div>

      <div className="flex-1 overflow-auto p-2.5 flex flex-col gap-2">
        {loading ? (
          <div className="text-micro text-ag-ink3 p-2">{t('recycle.loading')}</div>
        ) : bin.nodes.length === 0 ? (
          <EmptyState>{t('recycle.empty')}</EmptyState>
        ) : bin.nodes.map((n) => (
          <div key={n.id} className="flex items-center gap-2 rounded-card border border-ag-line2 bg-ag-bg2 p-2">
            <EntityBadge type={n.entity_type} />
            <span className="flex-1 min-w-0">
              <span className="block text-caption text-ag-ink1 truncate">{n.name}</span>
              <span className="block text-micro text-ag-ink3 ag-mono">
                {n.deleted_at ? n.deleted_at.replace('T', ' ').slice(0, 16) : ''}
              </span>
            </span>
            <Button size="sm" variant="primary" disabled={busy} onClick={() => void restore([n.id])}>
              {t('recycle.restore')}
            </Button>
            <Button size="sm" variant="danger" disabled={busy} onClick={() => void purge([n.id])}>
              {t('recycle.purge')}
            </Button>
          </div>
        ))}
        {msg && <div className="text-micro text-ag-ink3 px-1">{msg}</div>}
      </div>

      {bin.nodes.length > 0 && (
        <div className="shrink-0 px-3 py-2 border-t border-ag-line1 flex items-center gap-2">
          <Button size="sm" variant="danger" disabled={busy} onClick={() => void purgeAll()}>
            {t('recycle.purgeAll')}
          </Button>
          <span className="text-micro text-ag-ink3 flex-1">{t('recycle.purgeAllHint')}</span>
        </div>
      )}
    </div>
  )
}
