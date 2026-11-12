import { useEffect, useState } from 'react'
import {
  getThemeMode, setThemeMode, watchSystemTheme,
  THEME_EVENT, type ThemeMode,
} from './theme'

export function useTheme() {
  const [mode, setMode] = useState<ThemeMode>(() => getThemeMode())

  useEffect(() => {
    const onChange = (event: Event) => {
      const detail = (event as CustomEvent).detail
      if (detail?.mode) setMode(detail.mode)
    }
    window.addEventListener(THEME_EVENT, onChange)
    const unwatch = watchSystemTheme()
    return () => {
      window.removeEventListener(THEME_EVENT, onChange)
      unwatch()
    }
  }, [])

  return { mode, setMode: setThemeMode }
}
