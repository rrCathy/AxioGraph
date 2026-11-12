import katex from 'katex'

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

// Auto-close unbalanced braces in LaTeX — prevents ParseError when content
// is truncated mid-macro (e.g. "\mathcal{N}= \text{" missing closing "}").
function balanceLatexBraces(latex: string): string {
  let depth = 0
  for (let i = 0; i < latex.length; i++) {
    if (latex[i] === '\\') { i++; continue }
    if (latex[i] === '{') depth++
    else if (latex[i] === '}') depth = Math.max(0, depth - 1)
  }
  // Strip trailing backslash (incomplete command like "\operat")
  let result = latex.replace(/\\$/, '')
  if (depth > 0) result += '}'.repeat(depth)
  return result
}

export default function MathContent({ text, className = '' }: Props) {
  if (!text) return null

  const safeText = fixUnicodeEscapes(text)

  // Split by $$...$$ (display) and $...$ (inline)
  const parts: Array<{ type: 'text' | 'display' | 'inline'; value: string }> = []
  let remaining = safeText

  // First, handle display math $$...$$
  while (remaining.includes('$$')) {
    const start = remaining.indexOf('$$')
    if (start > 0) parts.push({ type: 'text', value: remaining.slice(0, start) })
    const end = remaining.indexOf('$$', start + 2)
    if (end === -1) {
      parts.push({ type: 'text', value: remaining.slice(start) })
      remaining = ''
      break
    }
    parts.push({ type: 'display', value: remaining.slice(start + 2, end).trim() })
    remaining = remaining.slice(end + 2)
  }
  // Append any remaining text after the last $$ pair
  if (remaining) parts.push({ type: 'text', value: remaining })

  // Then handle inline math $...$ in remaining text pieces
  const finalParts: Array<{ type: 'text' | 'display' | 'inline'; value: string }> = []
  for (const part of parts) {
    if (part.type !== 'text') {
      finalParts.push(part)
      continue
    }
    let chunk = part.value
    while (chunk.includes('$')) {
      const s = chunk.indexOf('$')
      if (s > 0) finalParts.push({ type: 'text', value: chunk.slice(0, s) })
      const e = chunk.indexOf('$', s + 1)
      if (e === -1) {
        finalParts.push({ type: 'text', value: chunk.slice(s) })
        chunk = ''
        break
      }
      finalParts.push({ type: 'inline', value: chunk.slice(s + 1, e).trim() })
      chunk = chunk.slice(e + 1)
    }
    if (chunk) finalParts.push({ type: 'text', value: chunk })
  }

  if (finalParts.length === 0) finalParts.push({ type: 'text', value: text })

  return (
    <span className={className}>
      {finalParts.map((part, i) => {
        if (part.type === 'text') return <span key={i}>{part.value}</span>
        try {
          const formula = balanceLatexBraces(part.value)
          const html = katex.renderToString(formula, {
            throwOnError: false,
            displayMode: part.type === 'display',
            trust: false,
          })
          return (
            <span
              key={i}
              dangerouslySetInnerHTML={{ __html: html }}
              className={part.type === 'display' ? 'block my-2 text-center' : ''}
            />
          )
        } catch {
          return (
            <span key={i} className="text-ag-mathError">
              <span className="ag-sr-only">公式无法解析：</span>
              [{part.value}]
            </span>
          )
        }
      })}
    </span>
  )
}
