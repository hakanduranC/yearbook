import { useInfiniteQuery, useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useCallback, useMemo, useState } from 'react'
import { Button } from '~/components/Button'
import { ConfirmSheet } from '~/components/ConfirmSheet'
import { FaceChip } from '~/components/FaceChip'
import { Lightbox } from '~/components/Lightbox'
import { Sheet } from '~/components/Sheet'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import type { Face, MediaFilter } from '~/lib/api/types'
import { useDeleteMedia } from '~/lib/deleteMedia'
import { publicOrigin } from '~/lib/env'
import { flattenPages } from '~/lib/grouping'
import { useLikeMutation } from '~/lib/likes'
import { eventQuery } from '~/lib/queries/event'
import { mediaDetailQuery, mediaQuery } from '~/lib/queries/media'
import { faceCropUrl, faceNotPerson, mediaFacesQuery, peopleQuery } from '~/lib/queries/people'
import styles from '~/styles/pages/people.module.css'

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
  const remove = useDeleteMedia(slug)
  const [confirm, setConfirm] = useState(false)
  const [peopleOpen, setPeopleOpen] = useState(false)

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

  const doDelete = async () => {
    try {
      await remove.mutateAsync([photoId])
      toast(t('photos.deleted', { count: 1 }))
      setConfirm(false)
      close()
    } catch {
      toast(t('common.error'))
      setConfirm(false)
    }
  }

  if (!item) return null

  return (
    <>
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
        onPeople={event.faces_enabled === false ? undefined : () => setPeopleOpen(true)}
        onDelete={() => setConfirm(true)}
      />
      <ConfirmSheet
        open={confirm}
        title={t('photos.deleteTitle')}
        body={t('photos.deleteBody')}
        confirmLabel={t('common.delete')}
        danger
        busy={remove.isPending}
        onConfirm={doDelete}
        onClose={() => setConfirm(false)}
      />
      <PeopleSheet
        slug={slug}
        mediaId={photoId}
        open={peopleOpen}
        onClose={() => setPeopleOpen(false)}
      />
    </>
  )
}

function PeopleSheet({
  slug,
  mediaId,
  open,
  onClose,
}: {
  slug: string
  mediaId: string
  open: boolean
  onClose: () => void
}) {
  const t = useT()
  const toast = useToast()
  const faces = useQuery({ ...mediaFacesQuery(mediaId), enabled: open })
  const people = useQuery({ ...peopleQuery(slug), enabled: open })
  const [reported, setReported] = useState<ReadonlySet<string>>(() => new Set())
  const personOf = (face: Face) => people.data?.persons.find((p) => p.id === face.person_id)

  const report = async (face: Face) => {
    try {
      await faceNotPerson(face.id)
      setReported((prev) => new Set(prev).add(face.id))
      toast(t('lightbox.reported'))
    } catch {
      toast(t('common.error'))
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title={t('lightbox.peopleTitle')}>
      {faces.isPending ? (
        <p className={styles.muted}>{t('common.loading')}</p>
      ) : !faces.data?.length ? (
        <p className={styles.muted}>{t('lightbox.noFaces')}</p>
      ) : (
        <ul className={styles.faceList}>
          {faces.data.map((face) => {
            const person = personOf(face)
            return (
              <li key={face.id} className={styles.faceRow} data-face={face.id}>
                <FaceChip
                  name={person?.display_name}
                  you={person?.is_me}
                  src={face.crop_url ?? faceCropUrl(face.id)}
                  caption={person ? t('people.faces', { count: person.face_count }) : ''}
                  link={
                    face.person_id
                      ? {
                          to: '/e/$slug/people/$personId',
                          params: { slug, personId: face.person_id },
                        }
                      : undefined
                  }
                />
                {face.person_id && !reported.has(face.id) ? (
                  <Button variant="quiet" small onClick={() => report(face)} data-not-person>
                    {t('lightbox.wrongPerson')}
                  </Button>
                ) : reported.has(face.id) ? (
                  <span className={styles.muted}>{t('lightbox.reported')}</span>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
    </Sheet>
  )
}
