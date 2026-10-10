import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from 'react'
import styles from './Toast.module.css'

interface ToastItem {
  id: number
  message: ReactNode
}

const ToastContext = createContext<(message: ReactNode) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const counter = useRef(0)
  const show = useCallback((message: ReactNode) => {
    const id = ++counter.current
    setItems((prev) => [...prev.slice(-2), { id, message }])
    setTimeout(() => setItems((prev) => prev.filter((i) => i.id !== id)), 2800)
  }, [])
  const value = useMemo(() => show, [show])
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className={styles.region} aria-live="polite" aria-atomic="true">
        {items.map((item) => (
          <div key={item.id} className={styles.toast} role="status">
            {item.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  return useContext(ToastContext)
}
