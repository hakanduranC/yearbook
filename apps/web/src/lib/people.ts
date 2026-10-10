import type { Person } from '~/lib/api/types'

/** Persons grouped by event, keeping the event order of the list. */
export function groupByEvent(persons: readonly Person[]): Array<[string, Person[]]> {
  const groups = new Map<string, Person[]>()
  for (const p of persons) {
    const list = groups.get(p.event_slug) ?? []
    list.push(p)
    groups.set(p.event_slug, list)
  }
  return [...groups.entries()]
}
