import { useMemo, useState } from 'react'
import type { GraphData } from '../../types'
import { ENTITY_META, entityKeyOf, type EntityKey } from '../../theme/entityMeta'
import { EntityBadge } from '../ui/Badge'
import EmptyState from '../ui/EmptyState'

interface Props {
  graphData: GraphData | null
  typeFilter: EntityKey | null
  setTypeFilter: (k: EntityKey | null) => void
  listMode: boolean
  setListMode: (v: boolean) => void
  selectedNodeId: string | null
  onSelect: (id: string) => void
}

const KEYS: EntityKey[] = ['def', 'the', 'lem', 'ex', 'pro', 'cor', 'other']

/** Keyboard/screen-reader equivalent of the Cytoscape canvas + type filter. */
export default function GraphA11yPanel({
  graphData, typeFilter, setTypeFilter, listMode, setListMode,
  selectedNodeId, onSelect,
}: Props) {
  const [query, setQuery] = useState('')

  const nodes = useMemo(() => graphData?.elements.nodes ?? [], [graphData])
  const counts = useMemo(() => {
    const acc: Record<string, number> = {}
    for (const n of nodes) {
      const k = entityKeyOf(n.data.entity_type)
      acc[k] = (acc[k] ?? 0) + 1
    }
    return acc
  }, [nodes])

  const visible = useMemo(() => nodes.filter((n) => {
    if (typeFilter && entityKeyOf(n.data.entity_type) !== typeFilter) return false
    if (query && !n.data.name.toLowerCase().includes(query.toLowerCase())) return false
    return true
  }), [nodes, typeFilter, query])

  return (
    <div className="absolute top-3 left-3 z-20 w-[272px] max-h-[calc(100%-24px)] flex flex-col rounded-overlay border border-ag-line2 bg-ag-bg3 overflow-hidden">
      <div className="shrink-0 flex border-b border-ag-line1 bg-ag-bg1">
        <button
          onClick={() => setListMode(false)}
          className={`ag-focus-ring flex-1 py-2 text-caption border-b-2 ${!listMode ? 'border-ag-cinnabar text-ag-ink1' : 'border-transparent text-ag-ink3'}`}
        >
          类型筛选
        </button>
        <button
          onClick={() => setListMode(true)}
          className={`ag-focus-ring flex-1 py-2 text-caption border-b-2 ${listMode ? 'border-ag-cinnabar text-ag-ink1' : 'border-transparent text-ag-ink3'}`}
          aria-label="切换到节点列表，键盘与读屏可用的等价视图"
        >
          节点列表
        </button>
      </div>

      {!listMode ? (
        <div className="p-3 flex flex-wrap gap-2 overflow-auto">
          {KEYS.map((k) => {
            const meta = ENTITY_META[k]
            const active = typeFilter === k
            return (
              <button
                key={k}
                onClick={() => setTypeFilter(active ? null : k)}
                aria-pressed={active}
                className={`ag-focus-ring flex items-center gap-1.5 px-2 py-1 rounded-badge border text-caption ${active ? 'border-ag-cinnabar text-ag-ink1' : 'border-ag-line1 text-ag-ink3 hover:text-ag-ink1'}`}
              >
                <span className="inline-block w-1.5 h-1.5 rounded-dot" style={{ backgroundColor: `var(${meta.colorVar})` }} aria-hidden="true" />
                <span className="ag-mono text-micro">{meta.abbr}</span>
                <span>{meta.label}</span>
                <span className="ag-mono text-micro text-ag-ink3">{counts[k] ?? 0}</span>
              </button>
            )
          })}
          {typeFilter && (
            <button onClick={() => setTypeFilter(null)} className="ag-focus-ring text-caption text-ag-cinnabar px-2 py-1">
              清除筛选
            </button>
          )}
        </div>
      ) : (
        <div className="flex flex-col min-h-0">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="过滤节点名称"
            aria-label="按名称过滤节点"
            className="ag-focus-ring m-2 px-2 py-1 text-caption rounded-btn bg-ag-bg2 border border-ag-line2 text-ag-ink1"
          />
          <ul className="flex-1 overflow-auto border-t border-ag-line1" role="list">
            {visible.length === 0 && <li className="p-3"><EmptyState>没有匹配的节点</EmptyState></li>}
            {visible.map((n) => {
              const meta = ENTITY_META[entityKeyOf(n.data.entity_type)]
              const selected = selectedNodeId === n.data.id
              return (
                <li key={n.data.id}>
                  <button
                    onClick={() => onSelect(n.data.id)}
                    aria-label={`「${n.data.name}」，类型 ${meta.label}，来源 ${n.data.chapter || '未标注'}，第 ${visible.indexOf(n) + 1} 条，共 ${visible.length} 条`}
                    aria-current={selected ? 'true' : undefined}
                    className={`ag-focus-ring w-full text-left px-3 py-2 flex items-center gap-2 border-b border-ag-line1 ${selected ? 'bg-ag-quoteBg border-l-2 border-l-ag-quoteRail' : 'hover:bg-ag-bg4'}`}
                  >
                    <EntityBadge type={n.data.entity_type} showLabel={false} />
                    <span className="text-caption text-ag-ink1 flex-1 truncate">{n.data.name}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
