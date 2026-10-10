import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query'
import { forEachMediaQuery, removeItem } from '~/lib/live/applyLiveEvent'
import { keys } from '~/lib/queries/keys'
import { deleteMedia } from '~/lib/queries/media'

/** Drops items from every cached page of the event and their detail queries. */
export function removeFromCaches(queryClient: QueryClient, slug: string, ids: readonly string[]) {
  forEachMediaQuery(queryClient, slug, (data) => {
    let next = data
    for (const id of ids) next = removeItem(next, id)
    return next
  })
  for (const id of ids) queryClient.removeQueries({ queryKey: keys.mediaDetail(id) })
  queryClient.invalidateQueries({ queryKey: keys.highlights(slug) })
}

/** Deletes one or many items; the cache is patched optimistically and the event counts refetched. */
export function useDeleteMedia(slug: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (ids: string[]) => {
      const results = await Promise.allSettled(ids.map((id) => deleteMedia(id)))
      const failed = ids.filter((_, i) => results[i]?.status === 'rejected')
      if (failed.length === ids.length) throw new Error('delete failed')
      return { deleted: ids.filter((id) => !failed.includes(id)), failed }
    },
    onMutate: async (ids) => {
      await queryClient.cancelQueries({ queryKey: keys.mediaAll(slug) })
      const snapshots = queryClient
        .getQueryCache()
        .findAll({ queryKey: keys.mediaAll(slug) })
        .map((q) => [q.queryKey, q.state.data] as const)
      removeFromCaches(queryClient, slug, ids)
      return { snapshots }
    },
    onError: (_err, _ids, context) => {
      for (const [key, data] of context?.snapshots ?? []) queryClient.setQueryData(key, data)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: keys.event(slug), exact: true })
    },
  })
}
