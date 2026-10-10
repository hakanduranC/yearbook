import { useCallback, useState } from 'react'

export function useSelection() {
  const [active, setActive] = useState(false)
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const start = useCallback(() => setActive(true), [])
  const cancel = useCallback(() => {
    setActive(false)
    setSelected(new Set())
  }, [])

  return { active, selected, toggle, start, cancel }
}
