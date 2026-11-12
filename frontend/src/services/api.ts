const BASE = '/api'

export async function uploadBook(file: File) {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`${BASE}/books/upload`, { method: 'POST', body: fd })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function listBooks() {
  const res = await fetch(`${BASE}/books/`)
  return res.json()
}

export async function getBookStatus(bookId: string) {
  const res = await fetch(`${BASE}/books/${bookId}/status`)
  return res.json()
}

export async function getGraph(bookId: string) {
  const res = await fetch(`${BASE}/graph/${bookId}`)
  return res.json()
}

export async function getNodeDetail(nodeId: string) {
  const res = await fetch(`${BASE}/graph/node/${nodeId}`)
  if (!res.ok) throw new Error(`${res.status}: ${await res.text().catch(() => 'Unknown error')}`)
  return res.json()
}

export async function updateNode(nodeId: string, name: string, content: string) {
  const res = await fetch(`${BASE}/graph/node/${nodeId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, content }),
  })
  return res.json()
}

export async function deleteNode(nodeId: string) {
  const res = await fetch(`${BASE}/graph/node/${nodeId}`, { method: 'DELETE' })
  return res.json()
}

export async function searchNodes(bookId: string, query: string) {
  const res = await fetch(`${BASE}/graph/search/${bookId}?q=${encodeURIComponent(query)}`)
  return res.json()
}

export async function askQuestion(question: string, bookId?: string) {
  const res = await fetch(`${BASE}/chat/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, book_id: bookId || null }),
  })
  return res.json()
}

export async function translateText(text: string, targetLang: string = 'zh') {
  const res = await fetch(`${BASE}/graph/translate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, target_lang: targetLang }),
  })
  return res.json()
}

/* ── Page-level workbench ─────────────────────────────────────────── */

export const pageImageUrl = (bookId: string, pageNo: number, zoom?: number) =>
  `${BASE}/books/${bookId}/pages/${pageNo}/render${zoom != null ? `?zoom=${zoom.toFixed(2)}` : ''}`

export async function importPages(bookId: string) {
  const res = await fetch(`${BASE}/books/${bookId}/import-pages`, { method: 'POST' })
  return res.json()
}

export async function listPages(bookId: string) {
  const res = await fetch(`${BASE}/books/${bookId}/pages`)
  return res.json()
}

export async function getPage(bookId: string, pageNo: number) {
  const res = await fetch(`${BASE}/books/${bookId}/pages/${pageNo}`)
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json()
}

export async function getPageLayout(bookId: string, pageNo: number, includeFigure = false) {
  const res = await fetch(`${BASE}/books/${bookId}/pages/${pageNo}/layout?include_figure=${includeFigure}`)
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json()
}

export async function relayout(bookId: string) {
  const res = await fetch(`${BASE}/books/${bookId}/relayout`, { method: 'POST' })
  return res.json()
}

export async function savePageText(bookId: string, pageNo: number, text: string) {
  const res = await fetch(`${BASE}/books/${bookId}/pages/${pageNo}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  return res.json()
}

export async function submitOcr(bookId: string, pageNo: number, text: string, confidence: number) {
  const res = await fetch(`${BASE}/books/${bookId}/pages/${pageNo}/ocr`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, confidence }),
  })
  return res.json()
}

export async function extractWindow(bookId: string, start: number, end: number,
                                    signal?: AbortSignal, taskId?: string) {
  const res = await fetch(`${BASE}/books/${bookId}/extract`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(taskId ? { 'X-Task-Id': taskId } : {}),
    },
    body: JSON.stringify({ start, end }),
    signal,
  })
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json()
}

export async function listCandidates(bookId: string, status = 'pending') {
  const res = await fetch(`${BASE}/books/${bookId}/candidates?status=${status}`)
  return res.json()
}

export async function confirmCandidate(id: string, quote?: string) {
  const res = await fetch(`${BASE}/candidates/${id}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ quote: quote || null }),
  })
  return res.json()
}

export async function rejectCandidate(id: string) {
  const res = await fetch(`${BASE}/candidates/${id}/reject`, { method: 'POST' })
  return res.json()
}

export async function mergeCandidate(id: string, nodeId: string) {
  const res = await fetch(`${BASE}/candidates/${id}/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ node_id: nodeId }),
  })
  return res.json()
}

/* ── Review-loop capabilities (backend lands these in stage D) ── */

export async function previewCandidate(id: string) {
  const res = await fetch(`${BASE}/candidates/${id}/preview`)
  if (!res.ok) return null
  return res.json()
}

export async function undoAction(token: string) {
  const res = await fetch(`${BASE}/actions/${token}/undo`, { method: 'POST' })
  return res.ok
}

export async function cancelTask(taskId: string) {
  const res = await fetch(`${BASE}/tasks/${taskId}/cancel`, { method: 'POST' })
  return res.ok
}

export async function deleteBook(bookId: string) {
  const res = await fetch(`${BASE}/books/${bookId}`, { method: 'DELETE' })
  return res.json()
}

export async function clearConfirmedNodes(bookId: string) {
  const res = await fetch(`${BASE}/books/${bookId}/confirmed-nodes`, { method: 'DELETE' })
  return res.json()
}

export async function listConfirmedNodes(bookId: string, q = '') {
  const res = await fetch(`${BASE}/books/${bookId}/confirmed-nodes?q=${encodeURIComponent(q)}`)
  return res.json()
}

/* ── Book structure / vision OCR / auto mode ────────────────────────── */

export async function getStructure(bookId: string) {
  const res = await fetch(`${BASE}/books/${bookId}/structure`)
  return res.json()
}

export async function detectStructure(bookId: string,
                                      signal?: AbortSignal, taskId?: string) {
  const res = await fetch(`${BASE}/books/${bookId}/structure/detect`, {
    method: 'POST',
    headers: taskId ? { 'X-Task-Id': taskId } : undefined,
    signal,
  })
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json()
}

export async function saveStructure(bookId: string, data: unknown) {
  const res = await fetch(`${BASE}/books/${bookId}/structure`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json()
}

export async function confirmStructure(bookId: string) {
  const res = await fetch(`${BASE}/books/${bookId}/structure/confirm`, { method: 'POST' })
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json()
}

export async function parseTocPage(bookId: string, pageNo: number) {
  const res = await fetch(`${BASE}/books/${bookId}/structure/toc-page`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ page_no: pageNo }),
  })
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json()
}

export async function visionOcr(bookId: string, pageNo: number,
                                taskId?: string, signal?: AbortSignal) {
  const res = await fetch(`${BASE}/books/${bookId}/pages/${pageNo}/vision-ocr`, {
    method: 'POST',
    headers: taskId ? { 'X-Task-Id': taskId } : undefined,
    signal,
  })
  if (!res.ok && res.status !== 404) {
    throw new Error(`${res.status}: ${await res.text()}`)
  }
  return res.json()
}

export async function startAutoExtract(bookId: string, start: number,
                                       end: number, windowSize: number) {
  const res = await fetch(`${BASE}/books/${bookId}/auto-extract`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ start, end, window_size: windowSize }),
  })
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json()
}

export async function getAutoStatus(bookId: string, taskId: string) {
  const res = await fetch(`${BASE}/books/${bookId}/auto-extract/${taskId}`)
  if (!res.ok) return null
  return res.json()
}
