import { statusMetaOf, entityMetaOf } from '../../theme/entityMeta'

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const meta = statusMetaOf(status)
  return (
    <span
      className={`ag-status ${meta.colorClass}`}
      style={{ backgroundColor: `color-mix(in srgb, var(${meta.colorVar}) 12%, transparent)` }}
      aria-label={`状态：${label ?? meta.label}`}
    >
      <span aria-hidden="true" className="ag-mono text-micro">{meta.icon}</span>
      <span>{label ?? meta.label}</span>
    </span>
  )
}

export function EntityBadge({ type, showLabel = true }: { type: string; showLabel?: boolean }) {
  const meta = entityMetaOf(type)
  return (
    <span className="inline-flex items-center gap-1.5 text-caption text-ag-ink3">
      <span
        className="inline-block w-1.5 h-1.5 rounded-dot shrink-0"
        style={{ backgroundColor: `var(${meta.colorVar})` }}
        aria-hidden="true"
      />
      <span className="ag-mono text-micro" style={{ color: `var(${meta.colorVar})` }}>
        {meta.abbr}
      </span>
      {showLabel && <span>{meta.label}</span>}
    </span>
  )
}
