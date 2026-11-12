import { create } from 'zustand'
import type { Book, GraphData } from '../types'

type Lang = 'zh' | 'en'

export interface UndoAction {
  id: string
  label: string
  expiresAt: number
  run: () => void
}

interface AppState {
  books: Book[]
  selectedBookId: string | null
  graphData: GraphData | null
  selectedNodeId: string | null
  chatMessages: { role: string; content: string; refs?: any[] }[]
  lang: Lang
  statusMessage: string
  alertMessage: string
  undoStack: UndoAction[]
  confirmedSummaryOpen: boolean

  setBooks: (b: Book[]) => void
  selectBook: (id: string) => void
  setGraphData: (d: GraphData | null) => void
  selectNode: (id: string | null) => void
  addChatMessage: (m: { role: string; content: string; refs?: any[] }) => void
  clearChat: () => void
  setLang: (l: Lang) => void
  setStatus: (m: string) => void
  setAlert: (m: string) => void
  pushUndo: (a: UndoAction) => void
  dropUndo: (id: string) => void
  setConfirmedSummaryOpen: (v: boolean) => void
}

export const useAppStore = create<AppState>((set) => ({
  books: [],
  selectedBookId: null,
  graphData: null,
  selectedNodeId: null,
  chatMessages: [],
  lang: 'zh',
  statusMessage: '',
  alertMessage: '',
  undoStack: [],
  confirmedSummaryOpen: true,

  setBooks: (books) => set({ books }),
  selectBook: (id) => set({ selectedBookId: id, graphData: null, selectedNodeId: null }),
  setGraphData: (data) => set({ graphData: data }),
  selectNode: (id) => set({ selectedNodeId: id }),
  addChatMessage: (msg) =>
    set((s) => ({ chatMessages: [...s.chatMessages, msg] })),
  clearChat: () => set({ chatMessages: [] }),
  setLang: (lang) => set({ lang }),
  setStatus: (m) => set({ statusMessage: m }),
  setAlert: (m) => set({ alertMessage: m }),
  pushUndo: (a) => set((s) => ({ undoStack: [...s.undoStack, a] })),
  dropUndo: (id) => set((s) => ({ undoStack: s.undoStack.filter((a) => a.id !== id) })),
  setConfirmedSummaryOpen: (v) => set({ confirmedSummaryOpen: v }),
}))
