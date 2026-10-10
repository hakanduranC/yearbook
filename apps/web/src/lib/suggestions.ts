import { useCallback, useSyncExternalStore } from 'react'
import type { Suggestion } from '~/lib/api/types'

const STORAGE_KEY = 'yb_dismissed_suggestions'

export type Dismissed = ReadonlySet<string>

export function dismiss(state: Dismissed, personId: string): Dismissed {
  if (state.has(personId)) return state
  const next = new Set(state)
  next.add(personId)
  return next
}

export function visibleSuggestions(
  list: readonly Suggestion[],
  dismissed: Dismissed,
): Suggestion[] {
  return list.filter((s) => !dismissed.has(s.person.id) && !s.person.is_me)
}

export function parseDismissed(raw: string | null | undefined): Dismissed {
  if (!raw) return new Set()
  try {
    const parsed: unknown = JSON.parse(raw)
    return new Set(Array.isArray(parsed) ? parsed.filter((x) => typeof x === 'string') : [])
  } catch {
    return new Set()
  }
}

export function serializeDismissed(state: Dismissed): string {
  return JSON.stringify([...state])
}

// Session-scoped store: dismissals survive navigation but not a new tab.
let memory: Dismissed | null = null
const listeners = new Set<() => void>()

function storage(): Storage | null {
  try {
    return typeof sessionStorage === 'undefined' ? null : sessionStorage
  } catch {
    return null
  }
}

function read(): Dismissed {
  if (memory) return memory
  memory = parseDismissed(storage()?.getItem(STORAGE_KEY))
  return memory
}

function write(next: Dismissed) {
  memory = next
  try {
    storage()?.setItem(STORAGE_KEY, serializeDismissed(next))
  } catch {
    // private mode or quota; the in-memory copy still works
  }
  for (const l of listeners) l()
}

const empty: Dismissed = new Set()

export function useDismissedSuggestions(): [Dismissed, (personId: string) => void] {
  const state = useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    read,
    () => empty,
  )
  const dismissOne = useCallback((personId: string) => write(dismiss(read(), personId)), [])
  return [state, dismissOne]
}
