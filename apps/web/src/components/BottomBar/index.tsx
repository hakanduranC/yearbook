import { createContext, type ReactNode, useContext, useEffect, useState } from 'react'
import styles from './BottomBar.module.css'

interface SlotApi {
  register: () => () => void
  present: boolean
}

const BottomBarContext = createContext<SlotApi | null>(null)

/** Provided by the event layout so pages reserve space for the bar when one is mounted. */
export function BottomBarProvider({ children }: { children: ReactNode }) {
  const [count, setCount] = useState(0)
  const api: SlotApi = {
    present: count > 0,
    register: () => {
      setCount((c) => c + 1)
      return () => setCount((c) => Math.max(0, c - 1))
    },
  }
  return <BottomBarContext.Provider value={api}>{children}</BottomBarContext.Provider>
}

export function useBottomBarPresent(): boolean {
  return useContext(BottomBarContext)?.present ?? false
}

export function BottomBar({ children, className }: { children: ReactNode; className?: string }) {
  const slot = useContext(BottomBarContext)
  const register = slot?.register
  useEffect(() => register?.(), [register])
  return (
    <div className={[styles.bar, 'no-print', className].filter(Boolean).join(' ')}>{children}</div>
  )
}
