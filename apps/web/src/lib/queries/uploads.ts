import { queryOptions } from '@tanstack/react-query'
import { api, ok, okVoid } from '~/lib/api/client'
import type {
  CompletedPart,
  GridItem,
  HostUploads,
  UploadFile,
  UploadInit,
  UploadStatus,
} from '~/lib/api/types'
import { keys } from './keys'

export async function createUploadIntents(
  slug: string,
  files: UploadFile[],
): Promise<UploadInit[]> {
  const res = ok(
    await api.POST('/events/{slug}/uploads', { params: { path: { slug } }, body: { files } }),
  )
  return res.uploads
}

export async function getUploadStatus(mediaId: string): Promise<UploadStatus> {
  return ok(await api.GET('/uploads/{media_id}', { params: { path: { media_id: mediaId } } }))
}

export async function completeUpload(mediaId: string, parts?: CompletedPart[]): Promise<GridItem> {
  return ok(
    await api.POST('/uploads/{media_id}/complete', {
      params: { path: { media_id: mediaId } },
      body: parts ? { parts } : undefined,
    }),
  )
}

export async function abortUpload(mediaId: string): Promise<void> {
  okVoid(await api.DELETE('/uploads/{media_id}', { params: { path: { media_id: mediaId } } }))
}

export function hostUploadsQuery(slug: string) {
  return queryOptions({
    queryKey: keys.hostUploads(slug),
    queryFn: async (): Promise<HostUploads> =>
      ok(await api.GET('/events/{slug}/uploads', { params: { path: { slug } } })),
  })
}

export async function retryMedia(mediaId: string): Promise<void> {
  okVoid(await api.POST('/media/{media_id}/retry', { params: { path: { media_id: mediaId } } }))
}
