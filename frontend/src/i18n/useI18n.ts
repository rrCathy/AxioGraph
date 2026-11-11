import { useAppStore } from '../stores/appStore'
import { t } from './translations'
import type { Lang } from './translations'

/**
 * Simple i18n hook. Returns:
 * - t: translation lookup function (dotted path)
 * - lang: current language
 * - setLang: switch language
 */
export function useI18n() {
  const lang = useAppStore((s) => s.lang)
  const setLang = useAppStore((s) => s.setLang)

  function translate(path: string): string {
    const keys = path.split('.')
    let node: any = t[lang]
    for (const key of keys) {
      if (node == null) return path
      node = node[key]
    }
    return typeof node === 'string' ? node : path
  }

  return { t: translate, lang, setLang }
}
