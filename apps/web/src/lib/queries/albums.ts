import { queryOptions } from '@tanstack/react-query'
import { api, ok, okVoid } from '~/lib/api/client'
import type { Album, AlbumCreate, AlbumDetail, AlbumUpdate, Share } from '~/lib/api/types'
import { keys } from './keys'

export function albumsQuery(slug: string) {
  return queryOptions({
    queryKey: keys.albums(slug),
    queryFn: async (): Promise<Album[]> =>
      ok(await api.GET('/events/{slug}/albums', { params: { path: { slug } } })).albums,
  })
}

export function albumQuery(id: string) {
  return queryOptions({
    queryKey: keys.album(id),
    queryFn: async (): Promise<AlbumDetail> =>
      ok(await api.GET('/albums/{album_id}', { params: { path: { album_id: id } } })),
  })
}

export function sharedAlbumQuery(shareId: string) {
  return queryOptions({
    queryKey: keys.share(shareId),
    queryFn: async (): Promise<AlbumDetail> =>
      ok(await api.GET('/s/{share_id}', { params: { path: { share_id: shareId } } })),
  })
}

export async function createAlbum(body: AlbumCreate): Promise<Album> {
  return ok(await api.POST('/albums', { body }))
}

export async function updateAlbum(id: string, body: AlbumUpdate): Promise<AlbumDetail> {
  return ok(await api.PATCH('/albums/{album_id}', { params: { path: { album_id: id } }, body }))
}

export async function deleteAlbum(id: string): Promise<void> {
  okVoid(await api.DELETE('/albums/{album_id}', { params: { path: { album_id: id } } }))
}

export async function shareAlbum(id: string, allow_download: boolean): Promise<Share> {
  return ok(
    await api.POST('/albums/{album_id}/share', {
      params: { path: { album_id: id } },
      body: { allow_download },
    }),
  )
}

/** The curated highlights album of an event, if the host made one. */
export function highlightsAlbum(albums: Album[] | undefined, title: string): Album | null {
  if (!albums) return null
  return (
    albums.find((a) => a.kind === 'highlights') ?? albums.find((a) => a.title === title) ?? null
  )
}
