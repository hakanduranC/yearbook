import { infiniteQueryOptions, queryOptions } from '@tanstack/react-query'
import { api, ok, okVoid } from '~/lib/api/client'
import type {
  CompletedPart,
  GridItem,
  Import,
  ImportCreate,
  ImportInit,
  MediaPage,
} from '~/lib/api/types'
import { keys } from './keys'
import { PAGE_SIZE } from './media'

export function importsQuery() {
  return queryOptions({
    queryKey: keys.imports(),
    queryFn: async (): Promise<Import[]> => ok(await api.GET('/imports')).imports,
  })
}

export function importQuery(id: string) {
  return queryOptions({
    queryKey: keys.import(id),
    queryFn: async (): Promise<Import> =>
      ok(await api.GET('/imports/{import_id}', { params: { path: { import_id: id } } })),
  })
}

export async function createImport(body: ImportCreate): Promise<ImportInit> {
  return ok(await api.POST('/imports', { body }))
}

export async function completeImport(id: string, parts?: CompletedPart[]): Promise<Import> {
  return ok(
    await api.POST('/imports/{import_id}/complete', {
      params: { path: { import_id: id } },
      body: parts ? { parts } : undefined,
    }),
  )
}

export async function cancelImport(id: string): Promise<void> {
  okVoid(await api.DELETE('/imports/{import_id}', { params: { path: { import_id: id } } }))
}

export function libraryQuery(unassigned: boolean) {
  return infiniteQueryOptions({
    queryKey: keys.library(unassigned),
    queryFn: async ({ pageParam }): Promise<MediaPage> =>
      ok(
        await api.GET('/me/library', {
          params: {
            query: { unassigned, limit: PAGE_SIZE, ...(pageParam ? { cursor: pageParam } : {}) },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
  })
}

export async function assignMediaEvent(id: string, event_slug: string | null): Promise<GridItem> {
  return ok(
    await api.PUT('/media/{media_id}/event', {
      params: { path: { media_id: id } },
      body: { event_slug },
    }),
  )
}

/** True while the API may still change the import; the page polls every 3 s in that case. */
export function importRunning(state: Import['state']): boolean {
  return state === 'uploading' || state === 'queued' || state === 'running'
}
