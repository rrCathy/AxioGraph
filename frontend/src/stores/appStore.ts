import { create } from 'zustand'
import type { Book, GraphData } from '../types'

type Lang = 'zh' | 'en'

interface AppState {
  books: Book[]
  selectedBookId: string | null
  graphData: GraphData | null
  selectedNodeId: string | null
  chatMessages: { role: string; content: string; refs?: any[] }[]
  lang: Lang

  setBooks: (b: Book[]) => void
  selectBook: (id: string) => void
  setGraphData: (d: GraphData | null) => void
  selectNode: (id: string | null) => void
  addChatMessage: (m: { role: string; content: string; refs?: any[] }) => void
  clearChat: () => void
  setLang: (l: Lang) => void
}

export const useAppStore = create<AppState>((set) => ({
  books: [],
  selectedBookId: null,
  graphData: null,
  selectedNodeId: null,
  chatMessages: [],
  lang: 'zh',

  setBooks: (books) => set({ books }),
  selectBook: (id) => set({ selectedBookId: id, graphData: null, selectedNodeId: null }),
  setGraphData: (data) => set({ graphData: data }),
  selectNode: (id) => set({ selectedNodeId: id }),
  addChatMessage: (msg) =>
    set((s) => ({ chatMessages: [...s.chatMessages, msg] })),
  clearChat: () => set({ chatMessages: [] }),
  setLang: (lang) => set({ lang }),
}))
