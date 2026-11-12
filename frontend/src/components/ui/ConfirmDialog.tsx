import { useEffect, useRef } from 'react'
import Button from './Button'

interface Props {
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  cancelLabel?: string
  destructive?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** Only for the danger whitelist. Focus starts on Cancel. */
export default function ConfirmDialog({
  open, title, description, confirmLabel = '确认', cancelLabel = '取消',
  destructive = false, onConfirm, onCancel,
}: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    cancelRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/60">
      <div
        role="dialog" aria-modal="true" aria-labelledby="ag-dialog-title"
        className="w-[min(420px,90vw)] rounded-overlay border border-ag-line2 bg-ag-bg3 p-5"
      >
        <h2 id="ag-dialog-title" className="text-h2 font-medium text-ag-ink1 mb-2">{title}</h2>
        <p className="text-body text-ag-ink2 mb-5 leading-relaxed">{description}</p>
        <div className="flex justify-end gap-2">
          <button
            ref={cancelRef}
            onClick={onCancel}
            className="ag-focus-ring h-8 px-3 rounded-btn text-body text-ag-ink2 border border-ag-line2 hover:bg-ag-bg4"
          >
            {cancelLabel}
          </button>
          <Button variant={destructive ? 'danger' : 'primary'} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
