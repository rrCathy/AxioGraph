import { useCallback, useEffect, useRef, useState } from 'react'

export type TaskKind = 'import' | 'extract' | 'ocr-download' | 'ocr-recognize'

export interface LongTaskState {
  active: boolean
  kind: TaskKind | null
  phase: string
  elapsedSec: number
  softExceeded: boolean
}

const INITIAL: LongTaskState = {
  active: false, kind: null, phase: '', elapsedSec: 0, softExceeded: false,
}

/** Deterministic elapsed timer, never a fake percentage. */
export function useLongTask(softThresholdSec = 75) {
  const [state, setState] = useState<LongTaskState>(INITIAL)
  const startedAt = useRef<number>(0)
  const tick = useRef<number | null>(null)

  const start = useCallback((kind: TaskKind, phase: string) => {
    startedAt.current = Date.now()
    setState({ active: true, kind, phase, elapsedSec: 0, softExceeded: false })
  }, [])

  const setPhase = useCallback((phase: string) => {
    setState((s) => (s.active ? { ...s, phase } : s))
  }, [])

  const stop = useCallback(() => {
    setState(INITIAL)
  }, [])

  useEffect(() => {
    if (!state.active) {
      if (tick.current !== null) window.clearInterval(tick.current)
      tick.current = null
      return
    }
    tick.current = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt.current) / 1000)
      setState((s) => s.active
        ? { ...s, elapsedSec: elapsed, softExceeded: elapsed >= softThresholdSec }
        : s)
    }, 1000)
    return () => {
      if (tick.current !== null) window.clearInterval(tick.current)
    }
  }, [state.active, softThresholdSec])

  const elapsedLabel = `${String(Math.floor(state.elapsedSec / 60)).padStart(2, '0')}:${String(state.elapsedSec % 60).padStart(2, '0')}`

  return { state, start, setPhase, stop, elapsedLabel }
}
