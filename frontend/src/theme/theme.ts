export type ThemeMode = 'dark' | 'light' | 'system'
export type ResolvedTheme = 'dark' | 'light'

const STORAGE_KEY = 'ag-theme'
export const THEME_EVENT = 'ag:themechange'

function isMode(value: string | null): value is ThemeMode {
  return value === 'dark' || value === 'light' || value === 'system'
}

function resolve(mode: ThemeMode): ResolvedTheme {
  if (mode !== 'system') return mode
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function getThemeMode(): ThemeMode {
  const stored = localStorage.getItem(STORAGE_KEY)
  return isMode(stored) ? stored : 'dark'
}

export function getResolvedTheme(): ResolvedTheme {
  const attr = document.documentElement.getAttribute('data-theme')
  return attr === 'light' ? 'light' : 'dark'
}

export function setThemeMode(mode: ThemeMode): void {
  const resolved = resolve(mode)
  const root = document.documentElement
  localStorage.setItem(STORAGE_KEY, mode)
  root.setAttribute('data-theme', resolved)
  root.setAttribute('data-theme-mode', mode)
  root.style.colorScheme = resolved
  window.dispatchEvent(
    new CustomEvent(THEME_EVENT, { detail: { mode, resolved } }),
  )
}

/** Re-apply on OS preference changes, but only when the user opted into system. */
export function watchSystemTheme(): () => void {
  const query = window.matchMedia('(prefers-color-scheme: dark)')
  const handler = () => {
    if (getThemeMode() === 'system') setThemeMode('system')
  }
  query.addEventListener('change', handler)
  return () => query.removeEventListener('change', handler)
}
