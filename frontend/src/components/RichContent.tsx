import katex from 'katex'
import { useMemo } from 'react'

interface Props {
  text: string
  className?: string
}

// Resolve literal unicode escapes like \u{26f3} that LLMs sometimes output
function fixUnicodeEscapes(text: string): string {
  return text.replace(/\\u\{([0-9A-Fa-f]+)\}/g, (_, hex) => {
    return String.fromCodePoint(parseInt(hex, 16))
  })
}

// Auto-close unbalanced braces in LaTeX
function balanceLatexBraces(latex: string): string {
  let depth = 0
  for (let i = 0; i < latex.length; i++) {
    if (latex[i] === '\\') { i++; continue }
    if (latex[i] === '{') depth++
    else if (latex[i] === '}') depth = Math.max(0, depth - 1)
  }
  let result = latex.replace(/\\$/, '')
  if (depth > 0) result += '}'.repeat(depth)
  return result
}

/**
 * Renders markdown-like text with TeX math support.
 * Renders bold/italic/code as actual React nodes, not HTML strings.
 */
export default function RichContent({ text, className = '' }: Props) {
  if (!text) return null

  const safeText = fixUnicodeEscapes(text)
  const blocks = safeText.split('\n\n')
  const processed: React.ReactNode[] = []

  for (let b = 0; b < blocks.length; b++) {
    const block = blocks[b].trim()
    if (!block) continue

    if (/^#{1,6}\s/.test(block)) {
      const level = block.match(/^(#{1,6})/)![1].length
      const content = block.replace(/^#{1,6}\s+/, '')
      const sizeClass = ['text-lg', 'text-base', 'text-sm'][Math.min(level, 3) - 1] || 'text-sm'
      processed.push(
        <div key={b} className={`font-semibold ${sizeClass} mt-3 mb-1 text-text-primary`}>
          <InlineSegments text={content} />
        </div>
      )
      continue
    }

    if (/^[-*_]{3,}$/.test(block)) {
      processed.push(<hr key={b} className="my-3 border-border-subtle" />)
      continue
    }

    if (block.startsWith('> ')) {
      processed.push(
        <blockquote key={b} className="border-l-2 border-accent-purple/50 pl-3 my-2 text-text-muted italic">
          <InlineSegments text={block.replace(/^> /gm, '')} />
        </blockquote>
      )
      continue
    }

    if (/^[-*+]\s/.test(block)) {
      const items = block.split('\n').filter(l => /^[-*+]\s/.test(l))
      processed.push(
        <ul key={b} className="list-disc pl-5 my-1 space-y-0.5">
          {items.map((item, i) => (
            <li key={i} className="text-text-secondary text-sm">
              <InlineSegments text={item.replace(/^[-*+]\s+/, '')} />
            </li>
          ))}
        </ul>
      )
      continue
    }

    if (/^\d+[.)]\s/.test(block)) {
      const items = block.split('\n').filter(l => /^\d+[.)]\s/.test(l))
      processed.push(
        <ol key={b} className="list-decimal pl-5 my-1 space-y-0.5">
          {items.map((item, i) => (
            <li key={i} className="text-text-secondary text-sm">
              <InlineSegments text={item.replace(/^\d+[.)]\s+/, '')} />
            </li>
          ))}
        </ol>
      )
      continue
    }

    if (block.startsWith('```')) {
      const lines = block.split('\n')
      const code = lines.slice(1, -1).join('\n')
      processed.push(
        <pre key={b} className="bg-surface-overlay rounded-lg p-3 my-2 overflow-x-auto">
          <code className="text-sm font-mono text-text-secondary">{code}</code>
        </pre>
      )
      continue
    }

    processed.push(
      <p key={b} className="text-sm text-text-secondary leading-relaxed my-1">
        <InlineSegments text={block} />
      </p>
    )
  }

  return <div className={className}>{processed}</div>
}

// ─── Inline segment tokenizer + renderer ──────────────────────

interface Seg { type: 'text' | 'display' | 'inline' | 'bold' | 'italic' | 'code'; value: string }

function tokenize(text: string): Seg[] {
  const segs: Seg[] = []
  let i = 0
  while (i < text.length) {
    // Display math: $$...$$ or \[...\]
    if (text.startsWith('$$', i)) {
      const end = text.indexOf('$$', i + 2)
      if (end !== -1) { segs.push({ type: 'display', value: text.slice(i + 2, end).trim() }); i = end + 2; continue }
    }
    if (text.startsWith('\\[', i)) {
      const end = text.indexOf('\\]', i + 2)
      if (end !== -1) { segs.push({ type: 'display', value: text.slice(i + 2, end).trim() }); i = end + 2; continue }
    }
    // Inline math: $...$ or \(...\)
    if (text[i] === '$') {
      const end = text.indexOf('$', i + 1)
      if (end !== -1) { segs.push({ type: 'inline', value: text.slice(i + 1, end).trim() }); i = end + 1; continue }
    }
    if (text.startsWith('\\(', i)) {
      const end = text.indexOf('\\)', i + 2)
      if (end !== -1) { segs.push({ type: 'inline', value: text.slice(i + 2, end).trim() }); i = end + 2; continue }
    }
    if (text.startsWith('**', i)) {
      const end = text.indexOf('**', i + 2)
      if (end !== -1) { segs.push({ type: 'bold', value: text.slice(i + 2, end) }); i = end + 2; continue }
    }
    if (text[i] === '`') {
      const end = text.indexOf('`', i + 1)
      if (end !== -1) { segs.push({ type: 'code', value: text.slice(i + 1, end) }); i = end + 1; continue }
    }
    if (text[i] === '*' && text[i - 1] !== '*' && text[i + 1] !== '*') {
      const end = text.indexOf('*', i + 1)
      if (end !== -1) { segs.push({ type: 'italic', value: text.slice(i + 1, end) }); i = end + 1; continue }
    }
    const start = i
    while (i < text.length && text[i] !== '$' && text[i] !== '*' && text[i] !== '`' && text[i] !== '\\') i++
    if (i > start) segs.push({ type: 'text', value: text.slice(start, i) })
    else i++
  }
  return segs
}

function InlineSegments({ text }: { text: string }) {
  const segs = useMemo(() => tokenize(text), [text])

  return (
    <>
      {segs.map((seg, idx) => {
        switch (seg.type) {
          case 'text':
            return <span key={idx}>{seg.value}</span>
          case 'display':
          case 'inline': {
            try {
              const formula = balanceLatexBraces(seg.value)
              const html = katex.renderToString(formula, {
                throwOnError: false, displayMode: seg.type === 'display', trust: false,
              })
              return <span key={idx} dangerouslySetInnerHTML={{ __html: html }} className={seg.type === 'display' ? 'block my-2 text-center' : ''} />
            } catch { return <span key={idx} className="text-red-400">[{seg.value}]</span> }
          }
          case 'bold':
            return <strong key={idx} className="font-semibold text-text-primary"><InlineSegments text={seg.value} /></strong>
          case 'italic':
            return <em key={idx}><InlineSegments text={seg.value} /></em>
          case 'code':
            return <code key={idx} className="px-1 py-0.5 bg-surface-overlay rounded text-xs font-mono text-accent-green">{seg.value}</code>
          default:
            return null
        }
      })}
    </>
  )
}
