/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  // Themes are driven by CSS variables in src/styles/tokens.css.
  // Do NOT enable darkMode or author `dark:` variants anywhere.
  theme: {
    extend: {
      colors: {
        ag: {
          bg0: 'var(--ag-bg-0)', bg1: 'var(--ag-bg-1)', bg2: 'var(--ag-bg-2)',
          bg3: 'var(--ag-bg-3)', bg4: 'var(--ag-bg-4)', bg5: 'var(--ag-bg-5)',
          mat: 'var(--ag-page-mat)', paper: 'var(--ag-paper)', linePaper: 'var(--ag-line-paper)',
          ink1: 'var(--ag-ink-1)', ink2: 'var(--ag-ink-2)', ink3: 'var(--ag-ink-3)',
          ink4: 'var(--ag-ink-4)',
          line1: 'var(--ag-line-1)', line2: 'var(--ag-line-2)', line3: 'var(--ag-line-3)',
          cinnabar: 'var(--ag-cinnabar)', cinnabarHover: 'var(--ag-cinnabar-hover)',
          cinnabarPress: 'var(--ag-cinnabar-press)', onCinnabar: 'var(--ag-on-cinnabar)',
          danger: 'var(--ag-danger)',
          entityDef: 'var(--ag-entity-def)', entityThe: 'var(--ag-entity-the)',
          entityLem: 'var(--ag-entity-lem)', entityEx: 'var(--ag-entity-ex)',
          entityPro: 'var(--ag-entity-pro)', entityCor: 'var(--ag-entity-cor)',
          entityDefBg: 'var(--ag-entity-def-bg)', entityTheBg: 'var(--ag-entity-the-bg)',
          entityLemBg: 'var(--ag-entity-lem-bg)', entityExBg: 'var(--ag-entity-ex-bg)',
          entityProBg: 'var(--ag-entity-pro-bg)', entityCorBg: 'var(--ag-entity-cor-bg)',
          statusPending: 'var(--ag-status-pending)', statusExtracted: 'var(--ag-status-extracted)',
          statusOcr: 'var(--ag-status-ocr)', statusReviewed: 'var(--ag-status-reviewed)',
          statusConfirmed: 'var(--ag-status-confirmed)', statusBad: 'var(--ag-status-bad)',
          statusMerged: 'var(--ag-status-merged)',
          selection: 'var(--ag-selection)', quoteBg: 'var(--ag-quote-bg)',
          quoteRail: 'var(--ag-quote-rail)', mathInk: 'var(--ag-math-ink)',
          mathError: 'var(--ag-math-error)', grid: 'var(--ag-grid)',
          focusInner: 'var(--ag-focus-inner)', focusOuter: 'var(--ag-focus-outer)',
          disabledBg: 'var(--ag-disabled-bg)', disabledInk: 'var(--ag-disabled-ink)',
          disabledLine: 'var(--ag-disabled-line)',
        },
        // Transition aliases: existing class names keep working but resolve to tokens.
        surface: {
          base: 'var(--ag-bg-0)', raised: 'var(--ag-bg-1)', overlay: 'var(--ag-bg-2)',
          card: 'var(--ag-bg-3)', hover: 'var(--ag-bg-4)',
        },
        accent: {
          blue: 'var(--ag-cinnabar)', purple: 'var(--ag-entity-the)',
          green: 'var(--ag-status-confirmed)', amber: 'var(--ag-status-ocr)',
          red: 'var(--ag-danger)', cyan: 'var(--ag-entity-lem)',
        },
        border: {
          subtle: 'var(--ag-line-1)', medium: 'var(--ag-line-2)', strong: 'var(--ag-line-3)',
        },
        text: {
          primary: 'var(--ag-ink-1)', secondary: 'var(--ag-ink-2)',
          muted: 'var(--ag-ink-3)', dim: 'var(--ag-ink-4)',
        },
      },
      fontFamily: {
        sans: ['AG UI', 'Inter', 'SF Pro Text', 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', 'sans-serif'],
        ui: ['AG UI', 'Inter', 'SF Pro Text', 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', 'sans-serif'],
        reading: ['AG Reading', 'Inter', 'Source Han Serif SC', 'Noto Serif SC', 'Songti SC', 'SimSun', 'serif'],
        mono: ['AG Mono', 'JetBrains Mono', 'SFMono-Regular', 'Consolas', 'monospace'],
      },
      fontSize: {
        display: ['24px', { lineHeight: '1.30' }],
        h1: ['20px', { lineHeight: '1.40' }],
        h2: ['17px', { lineHeight: '1.45' }],
        h3: ['15px', { lineHeight: '1.55' }],
        reading: ['16px', { lineHeight: '1.85' }],
        body: ['14px', { lineHeight: '1.60' }],
        caption: ['13px', { lineHeight: '1.55' }],
        micro: ['12px', { lineHeight: '1.50' }],
        // Legacy alias lifted from 10.4px to 13px: CJK at 10.4px is unreadable.
        '2xs': ['0.8125rem', { lineHeight: '1.5' }],
      },
      borderRadius: {
        page: '2px', body: '2px', btn: '6px', card: '8px', overlay: '10px',
        badge: '4px', dot: '9999px',
        xl: '10px', '2xl': '10px',
      },
      spacing: {
        topbar: '52px', tab: '40px', gutter: '24px', well: '20px', mat: '12px',
        rightx: '28px', righty: '24px', card: '12px', cardgap: '8px', inspector: '320px',
      },
      maxWidth: { page: '720px', measure: '38em' },
    },
  },
  plugins: [],
}
