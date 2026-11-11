import { useState } from 'react'
import Layout from './components/Layout'
import UploadBook from './components/UploadBook'
import GraphView from './components/GraphView'
import NodeDetail from './components/NodeDetail'
import ChatPanel from './components/ChatPanel'
import { useAppStore } from './stores/appStore'
import { useI18n } from './i18n/useI18n'

type Tab = 'books' | 'graph' | 'chat'

export default function App() {
  const { selectedNodeId, selectedBookId, books } = useAppStore()
  const { t, lang, setLang } = useI18n()
  const [tab, setTab] = useState<Tab>('books')

  const selectedBook = books.find((b) => b.id === selectedBookId)

  return (
    <Layout>
      <div className="flex flex-col h-full">
        {/* ─── Header ──────────────────────────────────── */}
        <header className="h-12 shrink-0 bg-surface-raised border-b border-border-subtle flex items-center px-4 gap-4">
          <div className="flex items-center gap-2.5">
            <span className="text-lg">{'\u29E1'}</span>
            <span className="font-semibold text-text-primary tracking-tight">{t('app.title')}</span>
            <span className="text-2xs text-text-muted bg-surface-overlay px-1.5 py-0.5 rounded">
              {t('app.subtitle')}
            </span>
          </div>

          {/* Separator */}
          <div className="w-px h-5 bg-border-medium" />

          {/* Tabs */}
          <nav className="flex items-center gap-0.5">
            <TabBtn active={tab === 'books'} onClick={() => setTab('books')} icon="\u{1F4DA}">
              {t('app.tabBooks')}
            </TabBtn>
            <TabBtn active={tab === 'graph'} onClick={() => setTab('graph')} icon="\u{26F3}">
              {t('app.tabGraph')}
            </TabBtn>
            <TabBtn active={tab === 'chat'} onClick={() => setTab('chat')} icon="\u{1F4AC}">
              {t('app.tabChat')}
            </TabBtn>
          </nav>

          {/* Book context + Language toggle */}
          <div className="ml-auto flex items-center gap-3">
            {tab === 'graph' && selectedBook && (
              <div className="flex items-center gap-2 text-xs text-text-secondary">
                <span className="w-1.5 h-1.5 rounded-full bg-accent-green" />
                <span className="text-text-muted">{t('app.current')}</span>
                <span className="text-text-primary font-medium truncate max-w-[200px]">
                  {selectedBook.title}
                </span>
              </div>
            )}
            <button
              onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
              className="px-2.5 py-1 text-xs font-medium rounded-md bg-surface-overlay border border-border-subtle text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors shrink-0"
              title={lang === 'zh' ? 'Switch to English' : '切换到中文'}
            >
              {t('app.langBtn')}
            </button>
          </div>
        </header>

        {/* ─── Content ─────────────────────────────────── */}
        <div className="flex-1 flex overflow-hidden">
          {tab === 'books' && (
            <div className="flex-1 overflow-auto">
              <div className="max-w-3xl mx-auto p-6">
                <div className="mb-8">
                  <h1 className="text-2xl font-bold text-text-primary tracking-tight">
                    {t('books.title')}
                  </h1>
                  <p className="text-sm text-text-muted mt-1">
                    {t('books.subtitle')}
                  </p>
                </div>
                <UploadBook />
              </div>
            </div>
          )}

          {tab === 'graph' && (
            <div className="flex-1 flex overflow-hidden">
              {/* Main graph area */}
              <div className="flex-1 relative">
                <GraphView />
              </div>

              {/* Right inspector panel */}
              <div className="w-80 shrink-0 bg-surface-overlay border-l border-border-subtle overflow-auto flex flex-col">
                <div className="px-4 py-2.5 border-b border-border-subtle shrink-0">
                  <p className="text-xs font-medium text-text-muted uppercase tracking-wider">
                    {t('app.inspector')}
                  </p>
                </div>
                <div className="flex-1 overflow-auto">
                  {selectedNodeId ? (
                    <NodeDetail nodeId={selectedNodeId} />
                  ) : (
                    <div className="p-4 text-sm text-text-muted">
                      <div className="text-center py-12">
                        <p className="text-3xl mb-3 opacity-30">{'\u{1F50D}'}</p>
                        <p className="text-text-secondary font-medium">{t('app.nodeInspector')}</p>
                        <p className="text-xs text-text-dim mt-1.5 leading-relaxed whitespace-pre-line">
                          {t('app.clickToView')}
                        </p>
                        <div className="mt-4 inline-flex items-center gap-1.5 text-2xs text-text-dim">
                          <span className="inline-block w-2 h-2 rounded-full bg-accent-blue" />
                          <span className="inline-block w-2 h-2 rounded-full bg-accent-green" />
                          <span className="inline-block w-2 h-2 rounded-full bg-accent-purple" />
                          <span className="inline-block w-2 h-2 rounded-full bg-accent-amber" />
                          <span className="inline-block w-2 h-2 rounded-full bg-accent-cyan" />
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {tab === 'chat' && (
            <div className="flex-1">
              <ChatPanel />
            </div>
          )}
        </div>
      </div>
    </Layout>
  )
}

function TabBtn({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean
  onClick: () => void
  icon: string
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-all duration-150
        ${active
          ? 'bg-surface-hover text-text-primary font-medium'
          : 'text-text-secondary hover:text-text-primary hover:bg-surface-overlay'}`}
    >
      <span className="text-base">{icon}</span>
      <span>{children}</span>
    </button>
  )
}
