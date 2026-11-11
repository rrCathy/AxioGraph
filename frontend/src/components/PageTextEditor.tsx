import { useEffect, useState } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'

const escapeHtml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

const toHtml = (text: string) =>
  text.split('\n').map((line) => `<p>${escapeHtml(line)}</p>`).join('') || '<p></p>'

interface Props {
  text: string
  onSave: (text: string) => void
  onQuote: (text: string) => void
  saving: boolean
  labels: {
    quote: string
    save: string
    saved: string
    selected: (n: number) => string
    chars: (n: number) => string
  }
}

/** Editable transcription of one PDF page. Selectable, quotable, correctable. */
export default function PageTextEditor({ text, onSave, onQuote, saving, labels }: Props) {
  const editor = useEditor({
    extensions: [StarterKit],
    content: toHtml(text),
    editorProps: { attributes: { class: 'page-editor-prose focus:outline-none' } },
  })
  const [selectedCount, setSelectedCount] = useState(0)
  const [dirty, setDirty] = useState(false)
  const [justSaved, setJustSaved] = useState(false)

  useEffect(() => {
    if (!editor || editor.getText() === text) return
    editor.commands.setContent(toHtml(text))
    setDirty(false)
    setJustSaved(false)
  }, [text, editor])

  useEffect(() => {
    if (!editor) return
    const onSelection = () => {
      const { from, to } = editor.state.selection
      setSelectedCount(editor.state.doc.textBetween(from, to, '\n').trim().length)
    }
    const onChange = () => setDirty(true)
    editor.on('selectionUpdate', onSelection)
    editor.on('update', onChange)
    return () => {
      editor.off('selectionUpdate', onSelection)
      editor.off('update', onChange)
    }
  }, [editor])

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
    setJustSaved(true)
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="shrink-0 flex items-center gap-2 px-3 py-2 border-b border-border-subtle bg-surface-raised">
        <span className="text-2xs text-text-muted flex-1">
          {selectedCount > 0 ? labels.selected(selectedCount) : labels.chars(text.length)}
        </span>
        <button
          onClick={quoteSelection}
          disabled={selectedCount === 0}
          className="px-2.5 py-1 text-xs rounded-md border border-border-subtle text-text-secondary hover:text-text-primary hover:bg-surface-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {labels.quote}
        </button>
        <button
          onClick={save}
          disabled={saving || (!dirty && !justSaved)}
          className="px-2.5 py-1 text-xs rounded-md bg-accent-blue text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {saving ? '...' : justSaved && !dirty ? labels.saved : labels.save}
        </button>
      </div>
      <div className="flex-1 overflow-auto px-4 py-3 bg-surface-overlay">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}
