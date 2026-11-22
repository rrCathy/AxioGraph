import { useEffect, useRef, useState } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Button from './ui/Button'

const escapeHtml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

const toHtml = (text: string) =>
  text.split('\n').map((line) => `<p>${escapeHtml(line)}</p>`).join('') || '<p></p>'

const FONT_SIZES = [13, 15, 16, 18, 20, 24] as const
const FONT_KEY = 'ag-editor-font-size'

function initialFontSize(): number {
  const saved = Number(localStorage.getItem(FONT_KEY))
  return FONT_SIZES.includes(saved as typeof FONT_SIZES[number]) ? saved : 15
}

interface Props {
  text: string
  onSave: (text: string) => void
  onQuote: (text: string) => void
  /** Promote the current selection to a graph node (opens the dialog). */
  onPromote: (text: string) => void
  /** Ask AI about the current selection (opens the dialog). */
  onAsk: (text: string) => void
  onDirtyChange?: (dirty: boolean) => void
  saving: boolean
}

interface SelPos { left: number; top: number }

export default function PageTextEditor({
  text, onSave, onQuote, onPromote, onAsk, onDirtyChange, saving,
}: Props) {
  const editor = useEditor({
    extensions: [StarterKit],
    content: toHtml(text),
    editorProps: {
      attributes: {
        class: 'page-editor-prose focus:outline-none',
        'aria-label': '本页提取文本，可编辑、可选中引用',
        spellcheck: 'false',
      },
    },
  })
  const [selectedCount, setSelectedCount] = useState(0)
  const [selPos, setSelPos] = useState<SelPos | null>(null)
  const [dirty, setDirty] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
  const [fontSize, setFontSize] = useState(initialFontSize)
  const scrollRef = useRef<HTMLDivElement>(null)

  const changeFontSize = (px: number) => {
    setFontSize(px)
    localStorage.setItem(FONT_KEY, String(px))
  }

  useEffect(() => {
    if (!editor || editor.getText() === text) return
    editor.commands.setContent(toHtml(text))
    setDirty(false)
    setJustSaved(false)
    onDirtyChange?.(false)
  }, [text, editor, onDirtyChange])

  useEffect(() => {
    if (!editor) return
    const onSelection = () => {
      const { from, to } = editor.state.selection
      const selected = editor.state.doc.textBetween(from, to, '\n').trim()
      setSelectedCount(selected.length)
      if (!selected.length || from === to) {
        setSelPos(null)
        return
      }
      // Anchor the toolbar at the selection start, clamped inside the pane.
      try {
        const start = editor.view.coordsAtPos(from)
        const pane = scrollRef.current?.getBoundingClientRect()
        if (pane) {
          setSelPos({
            left: Math.max(8, Math.min(start.left - pane.left, pane.width - 260)),
            top: Math.max(4, start.top - pane.top - 44),
          })
        }
      } catch {
        setSelPos(null)
      }
    }
    const onChange = () => {
      setDirty(true)
      onDirtyChange?.(true)
    }
    editor.on('selectionUpdate', onSelection)
    editor.on('update', onChange)
    return () => {
      editor.off('selectionUpdate', onSelection)
      editor.off('update', onChange)
    }
  }, [editor, onDirtyChange])

  // Hide the floating bar while the pane scrolls — it would drift away from
  // the text it refers to; the header buttons still work for the selection.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onScroll = () => setSelPos(null)
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  const withSelection = (fn: (s: string) => void) => {
    if (!editor) return
    const { from, to } = editor.state.selection
    const selected = editor.state.doc.textBetween(from, to, '\n').trim()
    if (selected) fn(selected)
  }

  const quoteSelection = () => withSelection(onQuote)
  const promoteSelection = () => { withSelection(onPromote); setSelPos(null) }
  const askSelection = () => { withSelection(onAsk); setSelPos(null) }

  const save = () => {
    if (!editor) return
    onSave(editor.getText())
    setDirty(false)
    onDirtyChange?.(false)
    setJustSaved(true)
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="shrink-0 flex items-center gap-2 px-3 py-2 border-b border-ag-line1 bg-ag-bg1">
        <span className="text-caption text-ag-ink3 flex-1 ag-mono">
          {selectedCount > 0 ? `已选 ${selectedCount} 字` : `${text.length} 字符`}
        </span>
        <label className="flex items-center gap-1.5 text-caption text-ag-ink3">
          <span className="shrink-0">字号</span>
          <select
            value={fontSize}
            onChange={(e) => changeFontSize(Number(e.target.value))}
            className="ag-focus-ring bg-ag-bg2 border border-ag-line2 rounded-btn px-1.5 py-0.5 text-caption text-ag-ink1"
            aria-label="提取文本字号"
          >
            {FONT_SIZES.map((px) => <option key={px} value={px}>{px}px</option>)}
          </select>
        </label>
        <Button size="sm" variant="ghost" onClick={promoteSelection} disabled={selectedCount === 0}>
          提升
        </Button>
        <Button size="sm" variant="ghost" onClick={askSelection} disabled={selectedCount === 0}>
          问 AI
        </Button>
        <Button size="sm" onClick={quoteSelection} disabled={selectedCount === 0}>
          引用选中
        </Button>
        <Button size="sm" variant="primary" onClick={save} loading={saving} disabled={!dirty && !justSaved}>
          {justSaved && !dirty ? '已保存' : '保存文本'}
        </Button>
      </div>
      <div
        ref={scrollRef}
        className="flex-1 overflow-auto ag-right-pane bg-ag-bg2 relative"
        style={{ padding: '24px 28px' }}
      >
        {selPos && (
          <div
            className="absolute z-20 flex items-center gap-1 rounded-btn border border-ag-line2 bg-ag-bg3 px-1.5 py-1 shadow-overlay"
            style={{ left: selPos.left, top: selPos.top }}
            role="toolbar"
            aria-label="选中文字操作"
          >
            <Button size="sm" variant="primary" onClick={promoteSelection}>提升</Button>
            <Button size="sm" onClick={askSelection}>问 AI</Button>
            <Button size="sm" variant="ghost" onClick={quoteSelection}>引用</Button>
          </div>
        )}
        <div
          style={{ maxWidth: 'var(--ag-measure)', '--ag-editor-fs': `${fontSize}px` } as React.CSSProperties}
        >
          <EditorContent editor={editor} />
        </div>
      </div>
    </div>
  )
}
