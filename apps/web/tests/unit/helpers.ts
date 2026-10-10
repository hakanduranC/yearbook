import type { GridItem, MediaGroup, MediaPage } from '~/lib/api/types'

export function item(overrides: Partial<GridItem> & { id: string }): GridItem {
  return {
    kind: 'photo',
    state: 'ready',
    captured_at: '2026-06-14T20:00:00Z',
    captured_src: 'exif',
    width: 4000,
    height: 3000,
    duration_ms: null,
    variants: {
      thumb: `https://cdn/v/${overrides.id}/thumb.webp`,
      small: `https://cdn/v/${overrides.id}/small.webp`,
    },
    like_count: 0,
    liked: false,
    me: false,
    mine: false,
    person_ids: [],
    score: null,
    processing: false,
    ...overrides,
  }
}

export function group(label: string, start: string, end: string, count = 0): MediaGroup {
  return { label, start, end, count }
}

export function page(
  items: GridItem[],
  groups: MediaGroup[] = [],
  next_cursor: string | null = null,
): MediaPage {
  return { items, groups, next_cursor }
}
