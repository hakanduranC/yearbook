import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { GridItem, MediaDetail } from '~/lib/api/types'
import { forEachMediaQuery, patchItem } from '~/lib/live/applyLiveEvent'
import { keys } from '~/lib/queries/keys'
import { likeMedia, unlikeMedia } from '~/lib/queries/media'

/** Optimistic like toggle across every cached page of the event plus the detail query. */
export function useLikeMutation(slug: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, liked }: { id: string; liked: boolean }) =>
      liked ? likeMedia(id) : unlikeMedia(id),
    onMutate: async ({ id, liked }) => {
      await queryClient.cancelQueries({ queryKey: keys.mediaAll(slug) })
      const previousDetail = queryClient.getQueryData<MediaDetail>(keys.mediaDetail(id))
      const snapshots = queryClient
        .getQueryCache()
        .findAll({ queryKey: keys.mediaAll(slug) })
        .map((q) => [q.queryKey, q.state.data] as const)
      const delta = liked ? 1 : -1
      const apply = (item: GridItem) => ({
        liked,
        like_count: Math.max(0, item.like_count + (item.liked === liked ? 0 : delta)),
      })
      forEachMediaQuery(queryClient, slug, (data) => {
        if (!data) return data
        const current = data.pages.flatMap((p) => p.items).find((i) => i.id === id)
        return current ? patchItem(data, id, apply(current)) : data
      })
      if (previousDetail) {
        queryClient.setQueryData<MediaDetail>(keys.mediaDetail(id), {
          ...previousDetail,
          ...apply(previousDetail),
        })
      }
      return { snapshots, previousDetail }
    },
    onError: (_err, { id }, context) => {
      for (const [key, data] of context?.snapshots ?? []) queryClient.setQueryData(key, data)
      if (context?.previousDetail)
        queryClient.setQueryData(keys.mediaDetail(id), context.previousDetail)
    },
    onSuccess: (result) => {
      const patch = { liked: result.liked, like_count: result.like_count }
      forEachMediaQuery(queryClient, slug, (data) => patchItem(data, result.media_id, patch))
      queryClient.setQueryData<MediaDetail>(keys.mediaDetail(result.media_id), (old) =>
        old ? { ...old, ...patch } : old,
      )
    },
  })
}
