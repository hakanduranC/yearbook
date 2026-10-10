import { infiniteQueryOptions, queryOptions } from '@tanstack/react-query'
import { api, ok } from '~/lib/api/client'
import type { LikeResult, MediaDetail, MediaFilter, MediaPage, ZipTicket } from '~/lib/api/types'
import { keys } from './keys'

export const PAGE_SIZE = 60

export function mediaQuery(slug: string, filter: MediaFilter) {
  return infiniteQueryOptions({
    queryKey: keys.media(slug, filter),
    queryFn: async ({ pageParam }): Promise<MediaPage> =>
      ok(
        await api.GET('/events/{slug}/media', {
          params: {
            path: { slug },
            query: { filter, limit: PAGE_SIZE, ...(pageParam ? { cursor: pageParam } : {}) },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
  })
}

export function mediaDetailQuery(id: string) {
  return queryOptions({
    queryKey: keys.mediaDetail(id),
    queryFn: async (): Promise<MediaDetail> =>
      ok(await api.GET('/media/{media_id}', { params: { path: { media_id: id } } })),
  })
}

export async function likeMedia(id: string): Promise<LikeResult> {
  return ok(await api.PUT('/media/{media_id}/like', { params: { path: { media_id: id } } }))
}

export async function unlikeMedia(id: string): Promise<LikeResult> {
  return ok(await api.DELETE('/media/{media_id}/like', { params: { path: { media_id: id } } }))
}

export async function deleteMedia(id: string): Promise<void> {
  ok(await api.DELETE('/media/{media_id}', { params: { path: { media_id: id } } }))
}

export async function createZip(media_ids: string[]): Promise<ZipTicket> {
  return ok(await api.POST('/media/zip', { body: { media_ids, originals: true } }))
}

export function originalUrl(id: string): string {
  return `/api/v1/media/${encodeURIComponent(id)}/original`
}
