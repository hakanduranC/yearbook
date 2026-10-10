import type { GridItem, MediaGroup, MediaPage } from '~/lib/api/types'

export type GroupKey = 'morning' | 'afternoon' | 'evening' | 'night' | 'new' | 'other'

export interface Group {
  key: string
  label: GroupKey
  start: string | null
  end: string | null
  items: GridItem[]
}

export type Row =
  | { type: 'header'; key: string; group: Group; index: number }
  | { type: 'row'; key: string; group: Group; items: GridItem[]; first: number }

export interface RowModel {
  rows: Row[]
  items: GridItem[]
  indexById: Map<string, number>
}

const dayParts = new Set<GroupKey>(['morning', 'afternoon', 'evening', 'night'])

function labelOf(label: string): GroupKey {
  return dayParts.has(label as GroupKey) ? (label as GroupKey) : 'other'
}

/** Flattens pages, removing duplicates by id (optimistic inserts and live events can overlap pages). */
export function flattenPages(pages: readonly MediaPage[] | undefined): {
  items: GridItem[]
  groups: MediaGroup[]
} {
  const seen = new Set<string>()
  const items: GridItem[] = []
  const groupsByStart = new Map<string, MediaGroup>()
  for (const page of pages ?? []) {
    for (const item of page.items) {
      if (item.state === 'removed' || seen.has(item.id)) continue
      seen.add(item.id)
      items.push(item)
    }
    for (const group of page.groups) {
      const prev = groupsByStart.get(group.start)
      if (!prev) groupsByStart.set(group.start, group)
    }
  }
  const groups = [...groupsByStart.values()].sort((a, b) =>
    a.start < b.start ? 1 : a.start > b.start ? -1 : 0,
  )
  return { items, groups }
}

/** Assigns items to the server's time-of-day groups; items without a matching group go to a leading "new" group. */
export function groupItems(items: readonly GridItem[], groups: readonly MediaGroup[]): Group[] {
  const sorted = [...groups].sort((a, b) => (a.start < b.start ? 1 : a.start > b.start ? -1 : 0))
  const buckets: Group[] = sorted.map((g) => ({
    key: `${g.start}|${g.label}`,
    label: labelOf(g.label),
    start: g.start,
    end: g.end,
    items: [],
  }))
  const fresh: Group = { key: 'new', label: 'new', start: null, end: null, items: [] }
  const undated: Group = { key: 'other', label: 'other', start: null, end: null, items: [] }

  for (const item of items) {
    const at = item.captured_at
    if (!at) {
      ;(item.state === 'ready' ? undated : fresh).items.push(item)
      continue
    }
    const bucket = buckets.find(
      (b) => b.start !== null && b.end !== null && at >= b.start && at < b.end,
    )
    if (bucket) bucket.items.push(item)
    else fresh.items.push(item)
  }
  const result: Group[] = []
  if (fresh.items.length) result.push(fresh)
  for (const b of buckets) if (b.items.length) result.push(b)
  if (undated.items.length) result.push(undated)
  return result
}

/** Builds the virtualizer row model: one header row per group, then rows of `columns` items. */
export function buildRows(groups: readonly Group[], columns: number): RowModel {
  const cols = Math.max(1, Math.floor(columns))
  const rows: Row[] = []
  const flat: GridItem[] = []
  const indexById = new Map<string, number>()
  for (const group of groups) {
    rows.push({ type: 'header', key: `h:${group.key}`, group, index: rows.length })
    for (let i = 0; i < group.items.length; i += cols) {
      const slice = group.items.slice(i, i + cols)
      rows.push({
        type: 'row',
        key: `r:${group.key}:${i}`,
        group,
        items: slice,
        first: flat.length,
      })
      for (const item of slice) {
        indexById.set(item.id, flat.length)
        flat.push(item)
      }
    }
  }
  return { rows, items: flat, indexById }
}

export function rowModel(pages: readonly MediaPage[] | undefined, columns: number): RowModel {
  const { items, groups } = flattenPages(pages)
  return buildRows(groupItems(items, groups), columns)
}

/** Columns by viewport width: 3 under 600, 5 under 1024, 6 under 1440, else 8. */
export function columnsFor(width: number): number {
  if (width < 600) return 3
  if (width < 1024) return 5
  if (width < 1440) return 6
  return 8
}
