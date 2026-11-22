import { lazy, Suspense, useState } from 'react'
import Layout from './components/Layout'
import Workbench from './components/Workbench'
const UploadBook = lazy(() => import('./components/UploadBook'))
const GraphView = lazy(() => import('./components/GraphView'))
const NodeDetail = lazy(() => import('./components/NodeDetail'))
const ChatPanel = lazy(() => import('./components/ChatPanel'))
import EmptyState from './components/ui/EmptyState'
import { useAppStore } from './stores/appStore'
import { useI18n } from './i18n/useI18n'
import { useTheme } from './theme/useTheme'
import type { ThemeMode } from './theme/theme'

type Tab = 'workbench' | 'books' | 'graph' | 'chat'

export default function App() {
  const { selectedNodeId, selectedBookId, books } = useAppStore()
  const { t, lang, setLang } = useI18n()
  const { mode, setMode } = useTheme()
  const [tab, setTab] = useState<Tab>('workbench')

  const selectedBook = books.find((b) => b.id === selectedBookId)

  return (
    <Layout>
      <div className="flex flex-col h-full min-h-0">
        <header className="h-topbar shrink-0 bg-ag-bg1 border-b border-ag-line1 flex items-center px-4 gap-4">
          <div className="flex items-center gap-2.5">
            <span className="text-h2 text-ag-cinnabar" aria-hidden="true">◇</span>
            <span className="font-reading text-[17px] font-semibold text-ag-ink1 tracking-tight">
              {t('app.title')}
            </span>
            <span className="text-caption text-ag-ink3 bg-ag-bg2 px-1.5 py-0.5 rounded-badge ag-mono">
              {t('app.subtitle')}
            </span>
          </div>

          <div className="w-px h-5 bg-ag-line2" />

          <nav className="flex items-center gap-6 h-tab" role="tablist" aria-label="主导航">
            <TabBtn active={tab === 'workbench'} onClick={() => setTab('workbench')}>
              {t('app.tabWorkbench')}
            </TabBtn>
            <TabBtn active={tab === 'books'} onClick={() => setTab('books')}>
              {t('app.tabBooks')}
            </TabBtn>
            <TabBtn active={tab === 'graph'} onClick={() => setTab('graph')}>
              {t('app.tabGraph')}
            </TabBtn>
            <TabBtn active={tab === 'chat'} onClick={() => setTab('chat')}>
              {t('app.tabChat')}
            </TabBtn>
          </nav>

          <div className="ml-auto flex items-center gap-3">
            {tab === 'graph' && selectedBook && (
              <div className="flex items-center gap-2 text-caption text-ag-ink2">
                <span className="w-1.5 h-1.5 rounded-dot bg-ag-statusConfirmed" />
                <span className="text-ag-ink3">{t('app.current')}</span>
                <span className="text-ag-ink1 font-medium truncate max-w-[200px]">
                  {selectedBook.title}
                </span>
              </div>
            )}
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as ThemeMode)}
              aria-label="界面主题"
              className="ag-focus-ring text-caption px-2 py-1 rounded-btn bg-ag-bg2 border border-ag-line2 text-ag-ink2"
            >
              <option value="dark">暗房</option>
              <option value="light">纸本</option>
              <option value="system">跟随系统</option>
            </select>
            <button
              onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
              className="ag-focus-ring px-2.5 py-1 text-caption rounded-btn bg-ag-bg2 border border-ag-line2 text-ag-ink3 hover:text-ag-ink1 hover:bg-ag-bg4 transition-colors"
              title={lang === 'zh' ? 'Switch to English' : '切换到中文'}
            >
              {t('app.langBtn')}
            </button>
          </div>
        </header>

        <div className="flex-1 flex min-h-0 overflow-hidden">
          <Suspense fallback={<div className="p-6 flex-1"><EmptyState>正在加载…</EmptyState></div>}>
          {/* Workbench stays MOUNTED across tab switches (display toggle, not
              unmount): flipping to the graph and back must not reset the
              reader's page position or drop unsaved text edits. */}
          <div className={tab === 'workbench' ? 'flex-1 min-w-0' : 'hidden'}>
            <Workbench />
          </div>

          {tab === 'books' && (
            <div className="flex-1 overflow-auto">
              <div className="max-w-3xl mx-auto p-6">
                <div className="mb-8">
                  <h1 className="text-display font-medium text-ag-ink1 tracking-tight">
                    {t('books.title')}
                  </h1>
                  <p className="text-body text-ag-ink3 mt-1">{t('books.subtitle')}</p>
                </div>
                <UploadBook />
              </div>
            </div>
          )}

          {tab === 'graph' && (
            <div className="flex-1 flex min-h-0">
              <div className="flex-1 relative min-w-0">
                <GraphView />
              </div>
              <div className="w-inspector shrink-0 bg-ag-bg1 border-l border-ag-line1 flex flex-col">
                <div className="px-4 py-2.5 border-b border-ag-line1 shrink-0">
                  <p className="text-caption font-medium text-ag-ink3 ag-mono">
                    {t('app.inspector')}
                  </p>
                </div>
                <div className="flex-1 overflow-auto">
                  {selectedNodeId ? (
                    <NodeDetail nodeId={selectedNodeId} />
                  ) : (
                    <div className="p-4">
                      <EmptyState>{t('app.clickToView')}</EmptyState>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {tab === 'chat' && (
            <div className="flex-1 min-h-0">
              <ChatPanel />
            </div>
          )}
          </Suspense>
        </div>
      </div>
    </Layout>
  )
}

function TabBtn({
  active, onClick, children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`ag-focus-ring h-full px-1 text-body border-b-2 transition-colors
        ${active
          ? 'border-ag-cinnabar text-ag-ink1 font-medium'
          : 'border-transparent text-ag-ink3 hover:text-ag-ink1'}`}
    >
      {children}
    </button>
  )
}
