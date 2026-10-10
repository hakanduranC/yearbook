import { useInfiniteQuery, useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, Link, Outlet } from '@tanstack/react-router'
import { useState } from 'react'
import * as v from 'valibot'
import { BottomBar } from '~/components/BottomBar'
import { Button, ButtonLink } from '~/components/Button'
import { ConfirmSheet } from '~/components/ConfirmSheet'
import { EmptyState } from '~/components/EmptyState'
import { FilterChipRow } from '~/components/FilterChipRow'
import { PhotoGrid } from '~/components/PhotoGrid'
import { SearchInput } from '~/components/SearchInput'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import { isMediaFilter, type MediaFilter, personIdOf } from '~/lib/api/types'
import { useDeleteMedia } from '~/lib/deleteMedia'
import { flattenPages } from '~/lib/grouping'
import { loadEvent } from '~/lib/guards'
import { savedCommandsQuery } from '~/lib/queries/agent'
import { eventQuery, isHost } from '~/lib/queries/event'
import { meQuery } from '~/lib/queries/me'
import { createZip, mediaQuery } from '~/lib/queries/media'
import { personQuery } from '~/lib/queries/people'
import { useSelection } from '~/lib/selection'
import styles from '~/styles/pages/photos.module.css'

const searchSchema = v.object({
  filter: v.optional(v.custom<MediaFilter>(isMediaFilter)),
})

export const Route = createFileRoute('/e/$slug/photos')({
  validateSearch: searchSchema,
  loaderDeps: ({ search }) => ({ filter: search.filter ?? 'all' }),
  loader: async ({ context: { queryClient }, params, deps }) => {
    const event = await loadEvent(queryClient, params.slug)
    if (event.guest_view || isHost(event)) {
      await queryClient
        .ensureInfiniteQueryData(mediaQuery(params.slug, deps.filter))
        .catch(() => undefined)
    }
  },
  component: PhotosPage,
})

function PhotosPage() {
  const t = useT()
  const toast = useToast()
  const { slug } = Route.useParams()
  const search = Route.useSearch()
  const filter: MediaFilter = search.filter ?? 'all'
  const { data: event } = useSuspenseQuery(eventQuery(slug))
  const host = isHost(event)
  const canView = event.guest_view || host
  const media = useInfiniteQuery({ ...mediaQuery(slug, filter), enabled: canView })
  const me = useQuery(meQuery())
  const commands = useQuery({ ...savedCommandsQuery(slug), enabled: canView })
  const personId = personIdOf(filter)
  const person = useQuery({ ...personQuery(personId ?? ''), enabled: personId !== null })
  const selection = useSelection()
  const [zipping, setZipping] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const remove = useDeleteMedia(slug)

  const { items } = flattenPages(media.data?.pages)
  const stillProcessing = event.counts.processing > 0
  const hasMe = Boolean(event.counts.of_you) || me.data?.has_claimed_person === true
  const [input, setInput] = useState('')

  const download = async () => {
    if (selection.selected.size === 0) return
    setZipping(true)
    toast(t('photos.preparingZip'))
    try {
      const ticket = await createZip([...selection.selected])
      window.location.assign(ticket.url)
      selection.cancel()
    } catch {
      toast(t('common.error'))
    } finally {
      setZipping(false)
    }
  }

  const deleteSelected = async () => {
    const ids = [...selection.selected]
    try {
      const result = await remove.mutateAsync(ids)
      toast(t('photos.deleted', { count: result.deleted.length }))
      selection.cancel()
    } catch {
      toast(t('common.error'))
    } finally {
      setConfirmDelete(false)
    }
  }

  return (
    <>
      <main className={styles.main} data-photos>
        <header className={styles.head}>
          <div>
            <Link to="/e/$slug" params={{ slug }} className={styles.title}>
              {event.title}
            </Link>
            <div className={styles.counts}>
              {t('event.counts', {
                photos: t('common.photos', { count: event.counts.photos }),
                videos: t('common.videos', { count: event.counts.videos }),
              })}
              {stillProcessing
                ? ` · ${t('event.stillFinding', { processing: event.counts.processing })}`
                : ''}
            </div>
          </div>
          {event.counts.of_you ? (
            <Link
              to="/e/$slug/photos"
              params={{ slug }}
              search={{ filter: 'me' }}
              className={styles.mePill}
              data-me-pill
            >
              {t('common.me')} · {event.counts.of_you}
            </Link>
          ) : null}
        </header>
        <FilterChipRow
          slug={slug}
          current={filter}
          hasMe={hasMe}
          personName={person.data?.is_me ? t('common.you') : person.data?.display_name}
          commands={commands.data ?? []}
        />
        {selection.active ? (
          <div className={styles.selectedCount} role="status">
            {t('photos.selected', { count: selection.selected.size })}
          </div>
        ) : null}
        {!canView ? (
          <EmptyState kind="no-photos" title={t('landing.viewOff')} body="" />
        ) : media.isError && !media.data ? (
          <EmptyState kind="offline" />
        ) : items.length === 0 && media.isSuccess ? (
          <EmptyState
            kind={filter === 'mine' ? 'mine' : stillProcessing ? 'analyzing' : 'no-photos'}
            action={
              filter === 'all' && !stillProcessing ? (
                <ButtonLink to="/e/$slug/upload" params={{ slug }}>
                  {t('photos.addPhotos')}
                </ButtonLink>
              ) : undefined
            }
          />
        ) : (
          <PhotoGrid
            slug={slug}
            filter={filter}
            pages={media.data?.pages}
            timeZone={event.timezone}
            selectMode={selection.active}
            selected={selection.selected}
            onToggle={selection.toggle}
            hasNextPage={media.hasNextPage}
            isFetchingNextPage={media.isFetchingNextPage}
            fetchNextPage={() => media.fetchNextPage()}
          />
        )}
      </main>
      {!selection.active && canView ? (
        <AskInput slug={slug} value={input} onChange={setInput} />
      ) : null}
      <BottomBar>
        {selection.active ? (
          <>
            <Button variant="secondary" onClick={selection.cancel}>
              {t('common.cancel')}
            </Button>
            {host ? (
              <Button
                variant="danger"
                onClick={() => setConfirmDelete(true)}
                disabled={selection.selected.size === 0}
                data-delete-selected
              >
                {t('photos.deleteN', { count: selection.selected.size })}
              </Button>
            ) : null}
            <Button
              onClick={download}
              disabled={selection.selected.size === 0}
              busy={zipping}
              data-download
            >
              {t('photos.downloadN', { count: selection.selected.size })}
            </Button>
          </>
        ) : (
          <>
            <ButtonLink to="/e/$slug/upload" params={{ slug }}>
              {t('photos.addPhotos')}
            </ButtonLink>
            <Button
              onClick={selection.start}
              disabled={items.length === 0}
              variant="secondary"
              data-select
            >
              {t('photos.select')}
            </Button>
          </>
        )}
      </BottomBar>
      <ConfirmSheet
        open={confirmDelete}
        title={t('photos.deleteNTitle', { count: selection.selected.size })}
        body={t('photos.deleteBody')}
        confirmLabel={t('photos.deleteN', { count: selection.selected.size })}
        danger
        busy={remove.isPending}
        onConfirm={deleteSelected}
        onClose={() => setConfirmDelete(false)}
      />
      <Outlet />
    </>
  )
}

/** The floating input hands the sentence to the search page. */
function AskInput({
  slug,
  value,
  onChange,
}: {
  slug: string
  value: string
  onChange: (v: string) => void
}) {
  const navigate = Route.useNavigate()
  return (
    <SearchInput
      value={value}
      onChange={onChange}
      onSubmit={(q) => navigate({ to: '/e/$slug/search', params: { slug }, search: { q } })}
    />
  )
}
