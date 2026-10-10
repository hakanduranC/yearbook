import type { Event, EventSummary } from '~/lib/api/types'

/** One row per event: the year's summary when the viewer appears in it, else the bare event. */
export interface HomeRow {
  slug: string
  title: string
  starts_at: string
  timezone?: string
  photos: number
  summary: EventSummary | null
  event: Event | null
}

export function homeRows(
  events: Event[] | undefined,
  summaries: EventSummary[] | undefined,
): HomeRow[] {
  const rows = new Map<string, HomeRow>()
  for (const s of summaries ?? []) {
    rows.set(s.slug, {
      slug: s.slug,
      title: s.title,
      starts_at: s.starts_at,
      photos: s.photos,
      summary: s,
      event: null,
    })
  }
  for (const e of events ?? []) {
    const existing = rows.get(e.slug)
    if (existing) {
      existing.event = e
      existing.timezone = e.timezone
    } else {
      rows.set(e.slug, {
        slug: e.slug,
        title: e.title,
        starts_at: e.starts_at,
        timezone: e.timezone,
        photos: e.counts.photos,
        summary: null,
        event: e,
      })
    }
  }
  return [...rows.values()].sort((a, b) => (a.starts_at < b.starts_at ? 1 : -1))
}
