import { useEffect } from 'react'
import { listBooks } from '../services/api'
import { useAppStore } from '../stores/appStore'

export default function Layout({ children }: { children: React.ReactNode }) {
  const setBooks = useAppStore((s) => s.setBooks)

  useEffect(() => {
    listBooks().then(setBooks).catch(() => {})
  }, [])

  return (
    <div className="h-screen w-screen flex flex-col bg-surface-base text-text-primary antialiased">
      <main className="flex-1 overflow-hidden">{children}</main>
    </div>
  )
}
