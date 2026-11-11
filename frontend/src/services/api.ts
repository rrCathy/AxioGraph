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

export async function pauseExtraction(bookId: string) {
  const res = await fetch(`${BASE}/books/${bookId}/pause`, { method: 'POST' })
  return res.json()
}

export async function resumeExtraction(bookId: string) {
  const res = await fetch(`${BASE}/books/${bookId}/resume`, { method: 'POST' })
  return res.json()
}

export async function cancelExtraction(bookId: string) {
  const res = await fetch(`${BASE}/books/${bookId}/cancel`, { method: 'POST' })
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
