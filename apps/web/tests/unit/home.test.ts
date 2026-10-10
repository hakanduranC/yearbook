import { describe, expect, it } from 'vitest'
import type { Event, EventSummary } from '~/lib/api/types'
import { homeRows } from '~/lib/home'
import { groupByEvent } from '~/lib/people'
import { item } from './helpers'

const event = (slug: string, starts_at: string): Event => ({
  id: `${slug}000000000000000000`.slice(0, 22),
  slug,
  title: slug,
  starts_at,
  timezone: 'Europe/Berlin',
  guest_upload: true,
  guest_view: true,
  host: { display_name: 'Mert' },
  counts: { photos: 10, videos: 1, ready: 11, processing: 0, failed: 0 },
  viewer: { role: 'owner' },
  created_at: starts_at,
})
const summary = (slug: string, starts_at: string, of_you: number): EventSummary => ({
  slug,
  title: slug,
  starts_at,
  photos: 20,
  of_you,
  of_you_items: Array.from({ length: Math.min(of_you, 4) }, (_, i) => item({ id: `${slug}-${i}` })),
})

describe('homeRows', () => {
  it('merges owned events with the year summaries, newest first', () => {
    const rows = homeRows(
      [event('party', '2026-06-14T18:00:00Z'), event('new', '2026-10-01T10:00:00Z')],
      [
        summary('party', '2026-06-14T18:00:00Z', 7),
        summary('guest-only', '2026-08-22T15:00:00Z', 2),
      ],
    )
    expect(rows.map((r) => r.slug)).toEqual(['new', 'guest-only', 'party'])
    const party = rows.find((r) => r.slug === 'party')
    expect(party?.summary?.of_you).toBe(7)
    expect(party?.event?.counts.photos).toBe(10)
    expect(party?.photos).toBe(20)
    expect(rows.find((r) => r.slug === 'new')?.summary).toBeNull()
    expect(rows.find((r) => r.slug === 'guest-only')?.event).toBeNull()
  })

  it('handles missing data on either side', () => {
    expect(homeRows(undefined, undefined)).toEqual([])
    expect(homeRows([event('a', '2026-01-01T00:00:00Z')], undefined)).toHaveLength(1)
  })
})

describe('groupByEvent', () => {
  it('keeps first-seen event order and groups persons', () => {
    const groups = groupByEvent([
      { id: 'p1', event_slug: 'b', face_count: 1, is_me: true, named: true, hidden: false },
      { id: 'p2', event_slug: 'a', face_count: 1, is_me: true, named: true, hidden: false },
      { id: 'p3', event_slug: 'b', face_count: 1, is_me: true, named: true, hidden: false },
    ])
    expect(groups.map(([slug, list]) => [slug, list.map((p) => p.id)])).toEqual([
      ['b', ['p1', 'p3']],
      ['a', ['p2']],
    ])
  })
})
