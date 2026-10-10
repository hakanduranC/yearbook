import type { MediaFilter } from '~/lib/api/types'

/** Key convention: ['me'], ['events'], ['event', slug, ...sub], ['media', id]. */
export const keys = {
  me: () => ['me'] as const,
  events: () => ['events'] as const,
  event: (slug: string) => ['event', slug] as const,
  eventAll: (slug: string) => ['event', slug] as const,
  media: (slug: string, filter: MediaFilter) => ['event', slug, 'media', filter] as const,
  mediaAll: (slug: string) => ['event', slug, 'media'] as const,
  status: (slug: string) => ['event', slug, 'status'] as const,
  hostUploads: (slug: string) => ['event', slug, 'uploads'] as const,
  mediaDetail: (id: string) => ['media', id] as const,
}
