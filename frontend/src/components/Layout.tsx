import { useEffect } from 'react'
import { listBooks } from '../services/api'
import { useAppStore } from '../stores/appStore'
import AriaLive from './ui/AriaLive'

export default function Layout({ children }: { children: React.ReactNode }) {
  const setBooks = useAppStore((s) => s.setBooks)

  useEffect(() => {
    listBooks().then(setBooks).catch(() => {})
  }, [])

  return (
    <div className="min-h-screen w-full flex flex-col bg-ag-bg0 text-ag-ink1 antialiased">
      <main className="flex-1 min-h-0 flex flex-col relative">{children}</main>
      <AriaLive />
    </div>
  )
}
