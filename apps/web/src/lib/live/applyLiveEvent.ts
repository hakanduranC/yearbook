import type { InfiniteData, QueryClient } from '@tanstack/react-query'
import { type GridItem, isMediaFilter, type MediaFilter, type MediaPage } from '~/lib/api/types'
import { keys } from '~/lib/queries/keys'

export type LiveEvent =
  | { type: 'media.queued'; data: { id: string; mine?: boolean } }
  | { type: 'media.ready'; data: GridItem }
  | { type: 'media.failed'; data: { id: string; code?: string } }
  | { type: 'media.removed'; data: { id: string } }
  | { type: 'like.changed'; data: { media_id: string; like_count: number } }
  | { type: 'people.updated'; data: { event_slug: string } }

export const liveEventNames = [
  'media.queued',
  'media.ready',
  'media.failed',
  'media.removed',
  'like.changed',
  'people.updated',
] as const

type MediaData = InfiniteData<MediaPage, string | null>

/** Whether a filter admits a grid item. */
export function filterAdmits(filter: MediaFilter, item: GridItem): boolean {
  switch (filter) {
    case 'all':
      return true
    case 'videos':
      return item.kind === 'video'
    case 'mine':
      return item.mine === true
    case 'me':
      return item.me === true
    case 'best':
      return item.score !== null && item.score !== undefined
    case 'library':
      return false
  }
  if (filter.startsWith('person:')) return item.person_ids.includes(filter.slice(7))
  // album:{id}: membership is curated, never inferred from a live event.
  return false
}

function filterOfKey(key: readonly unknown[]): MediaFilter | null {
  const f = key[3]
  return isMediaFilter(f) ? f : null
}

function mapPages(data: MediaData, fn: (page: MediaPage, index: number) => MediaPage): MediaData {
  return { ...data, pages: data.pages.map(fn) }
}

/** Replaces the item wherever it is, or prepends it to page 0 if the filter admits it. */
export function upsertItem(
  data: MediaData | undefined,
  item: GridItem,
  filter: MediaFilter,
): MediaData | undefined {
  if (!data) return data
  let found = false
  const next = mapPages(data, (page) => {
    const index = page.items.findIndex((i) => i.id === item.id)
    if (index === -1) return page
    found = true
    const items = page.items.slice()
    items[index] = item
    return { ...page, items }
  })
  if (found || !filterAdmits(filter, item)) return next
  const first = next.pages[0]
  if (!first)
    return {
      ...next,
      pages: [{ items: [item], groups: [], next_cursor: null }],
      pageParams: [null],
    }
  return {
    ...next,
    pages: [{ ...first, items: [item, ...first.items] }, ...next.pages.slice(1)],
  }
}

export function removeItem(data: MediaData | undefined, id: string): MediaData | undefined {
  if (!data) return data
  return mapPages(data, (page) =>
    page.items.some((i) => i.id === id)
      ? { ...page, items: page.items.filter((i) => i.id !== id) }
      : page,
  )
}

export function patchItem(
  data: MediaData | undefined,
  id: string,
  patch: Partial<GridItem>,
): MediaData | undefined {
  if (!data) return data
  return mapPages(data, (page) =>
    page.items.some((i) => i.id === id)
      ? { ...page, items: page.items.map((i) => (i.id === id ? { ...i, ...patch } : i)) }
      : page,
  )
}

/** Applies `fn` to every cached media list of the event, honoring each list's filter. */
export function forEachMediaQuery(
  queryClient: QueryClient,
  slug: string,
  fn: (data: MediaData | undefined, filter: MediaFilter) => MediaData | undefined,
) {
  const queries = queryClient.getQueryCache().findAll({ queryKey: keys.mediaAll(slug) })
  for (const query of queries) {
    const filter = filterOfKey(query.queryKey)
    if (!filter) continue
    queryClient.setQueryData<MediaData>(query.queryKey, (old) => fn(old, filter))
  }
}

/** Inserts (or replaces) a grid item in every cached list that admits it. Used by live events and optimistic uploads. */
export function insertGridItem(queryClient: QueryClient, slug: string, item: GridItem) {
  forEachMediaQuery(queryClient, slug, (data, filter) => upsertItem(data, item, filter))
}

export function applyLiveEvent(queryClient: QueryClient, slug: string, event: LiveEvent) {
  switch (event.type) {
    case 'media.ready':
      insertGridItem(queryClient, slug, event.data)
      queryClient.setQueryData(keys.mediaDetail(event.data.id), (old: unknown) =>
        old ? { ...(old as object), ...event.data } : old,
      )
      queryClient.invalidateQueries({ queryKey: keys.event(slug) })
      return
    case 'media.removed':
      forEachMediaQuery(queryClient, slug, (data) => removeItem(data, event.data.id))
      queryClient.removeQueries({ queryKey: keys.mediaDetail(event.data.id) })
      return
    case 'media.failed':
      forEachMediaQuery(queryClient, slug, (data) =>
        patchItem(data, event.data.id, { state: 'failed', processing: false }),
      )
      return
    case 'like.changed':
      forEachMediaQuery(queryClient, slug, (data) =>
        patchItem(data, event.data.media_id, { like_count: event.data.like_count }),
      )
      queryClient.setQueryData(keys.mediaDetail(event.data.media_id), (old: unknown) =>
        old ? { ...(old as object), like_count: event.data.like_count } : old,
      )
      return
    case 'media.queued':
      queryClient.invalidateQueries({ queryKey: keys.event(slug) })
      return
    case 'people.updated':
      // media.analyzed is not sent: people lists, person details and the event counts
      // (people, faces_done, of_you) all refresh here.
      queryClient.invalidateQueries({ queryKey: keys.people(slug) })
      queryClient.invalidateQueries({ queryKey: keys.event(slug), exact: true })
      queryClient.invalidateQueries({ queryKey: keys.personAll() })
      queryClient.invalidateQueries({ queryKey: keys.media(slug, 'me') })
      return
  }
}

export function parseLiveEvent(name: string, raw: string): LiveEvent | null {
  if (!(liveEventNames as readonly string[]).includes(name)) return null
  try {
    return { type: name, data: JSON.parse(raw) } as LiveEvent
  } catch {
    return null
  }
}
