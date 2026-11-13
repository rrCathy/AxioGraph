import { useEffect, useState } from 'react'
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
  onDirtyChange?: (dirty: boolean) => void
  saving: boolean
}

export default function PageTextEditor({
  text, onSave, onQuote, onDirtyChange, saving,
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
  const [dirty, setDirty] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
  const [fontSize, setFontSize] = useState(initialFontSize)

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
      setSelectedCount(editor.state.doc.textBetween(from, to, '\n').trim().length)
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

  const quoteSelection = () => {
    if (!editor) return
    const { from, to } = editor.state.selection
    const selected = editor.state.doc.textBetween(from, to, '\n').trim()
    if (selected) onQuote(selected)
  }

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
        <Button size="sm" onClick={quoteSelection} disabled={selectedCount === 0}>
          引用选中
        </Button>
        <Button size="sm" variant="primary" onClick={save} loading={saving} disabled={!dirty && !justSaved}>
          {justSaved && !dirty ? '已保存' : '保存文本'}
        </Button>
      </div>
      <div className="flex-1 overflow-auto ag-right-pane bg-ag-bg2" style={{ padding: '24px 28px' }}>
        <div
          style={{ maxWidth: 'var(--ag-measure)', '--ag-editor-fs': `${fontSize}px` } as React.CSSProperties}
        >
          <EditorContent editor={editor} />
        </div>
      </div>
    </div>
  )
}
