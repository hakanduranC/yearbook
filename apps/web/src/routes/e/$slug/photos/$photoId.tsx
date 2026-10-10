import { useInfiniteQuery, useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useCallback, useMemo } from 'react'
import { Lightbox } from '~/components/Lightbox'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import type { MediaFilter } from '~/lib/api/types'
import { publicOrigin } from '~/lib/env'
import { flattenPages } from '~/lib/grouping'
import { useLikeMutation } from '~/lib/likes'
import { eventQuery } from '~/lib/queries/event'
import { mediaDetailQuery, mediaQuery } from '~/lib/queries/media'

export const Route = createFileRoute('/e/$slug/photos/$photoId')({
  loader: async ({ context: { queryClient }, params }) => {
    const [event, item] = await Promise.all([
      queryClient.ensureQueryData(eventQuery(params.slug)),
      queryClient.ensureQueryData(mediaDetailQuery(params.photoId)).catch(() => null),
    ])
    return {
      origin: publicOrigin(),
      title: event.title,
      image: item?.variants?.large ?? item?.variants?.medium ?? item?.poster ?? null,
      width: item?.width ?? null,
      height: item?.height ?? null,
    }
  },
  head: ({ loaderData, params }) => {
    if (!loaderData) return {}
    const url = `${loaderData.origin}/e/${encodeURIComponent(params.slug)}/photos/${encodeURIComponent(params.photoId)}`
    return {
      meta: [
        { title: `${loaderData.title} · Yearbook` },
        { property: 'og:title', content: loaderData.title },
        { property: 'og:url', content: url },
        ...(loaderData.image
          ? [
              { property: 'og:image', content: loaderData.image },
              ...(loaderData.width
                ? [{ property: 'og:image:width', content: String(loaderData.width) }]
                : []),
              ...(loaderData.height
                ? [{ property: 'og:image:height', content: String(loaderData.height) }]
                : []),
              { name: 'twitter:card', content: 'summary_large_image' },
            ]
          : []),
      ],
    }
  },
  component: PhotoRoute,
})

function PhotoRoute() {
  const t = useT()
  const toast = useToast()
  const { slug, photoId } = Route.useParams()
  const search = Route.useSearch()
  const filter: MediaFilter = search.filter ?? 'all'
  const navigate = useNavigate()
  const { data: event } = useSuspenseQuery(eventQuery(slug))
  const detail = useQuery(mediaDetailQuery(photoId))
  const list = useInfiniteQuery(mediaQuery(slug, filter))
  const like = useLikeMutation(slug)

  const { items } = useMemo(() => flattenPages(list.data?.pages), [list.data?.pages])
  const index = items.findIndex((i) => i.id === photoId)
  const previous = index > 0 ? (items[index - 1] ?? null) : null
  const next = index >= 0 && index < items.length - 1 ? (items[index + 1] ?? null) : null
  const fromList = index >= 0 ? items[index] : undefined
  const item = detail.data
    ? {
        ...detail.data,
        ...(fromList ? { liked: fromList.liked, like_count: fromList.like_count } : {}),
      }
    : fromList

  // Pull the next page when the viewer reaches the last loaded item.
  if (index >= 0 && index >= items.length - 3 && list.hasNextPage && !list.isFetchingNextPage) {
    list.fetchNextPage()
  }

  const close = useCallback(() => {
    navigate({
      to: '/e/$slug/photos',
      params: { slug },
      search: filter === 'all' ? {} : { filter },
      resetScroll: false,
    })
  }, [navigate, slug, filter])

  const go = useCallback(
    (id: string) => {
      navigate({
        to: '/e/$slug/photos/$photoId',
        params: { slug, photoId: id },
        search: filter === 'all' ? {} : { filter },
        replace: true,
        resetScroll: false,
      })
    },
    [navigate, slug, filter],
  )

  if (!item) return null

  return (
    <Lightbox
      item={item}
      index={index + 1}
      total={items.length}
      previous={previous}
      next={next}
      eventTitle={event.title}
      timeZone={event.timezone}
      onClose={close}
      onNavigate={go}
      onToggleLike={(id, liked) => like.mutate({ id, liked })}
      onShared={(how) => {
        if (how === 'copied') toast(t('common.copied'))
      }}
    />
  )
}
