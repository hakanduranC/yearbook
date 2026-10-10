import { useInfiniteQuery, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, Link, Outlet } from '@tanstack/react-router'
import { useState } from 'react'
import * as v from 'valibot'
import { BottomBar } from '~/components/BottomBar'
import { Button, ButtonLink } from '~/components/Button'
import { EmptyState } from '~/components/EmptyState'
import { FilterChipRow } from '~/components/FilterChipRow'
import { PhotoGrid } from '~/components/PhotoGrid'
import { SearchInput } from '~/components/SearchInput'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import { type MediaFilter, mediaFilters } from '~/lib/api/types'
import { flattenPages } from '~/lib/grouping'
import { loadEvent } from '~/lib/guards'
import { eventQuery, isHost } from '~/lib/queries/event'
import { createZip, mediaQuery } from '~/lib/queries/media'
import { useSelection } from '~/lib/selection'
import styles from '~/styles/pages/photos.module.css'

const searchSchema = v.object({
  filter: v.optional(v.picklist(mediaFilters)),
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
  const canView = event.guest_view || isHost(event)
  const media = useInfiniteQuery({ ...mediaQuery(slug, filter), enabled: canView })
  const selection = useSelection()
  const [zipping, setZipping] = useState(false)

  const { items } = flattenPages(media.data?.pages)
  const stillProcessing = event.counts.processing > 0

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
            <Link to="/e/$slug/me" params={{ slug }} className={styles.mePill}>
              {t('common.me')} · {event.counts.of_you}
            </Link>
          ) : null}
        </header>
        <FilterChipRow slug={slug} current={filter} />
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
      {!selection.active ? <SearchInput disabled /> : null}
      <BottomBar>
        {selection.active ? (
          <>
            <Button variant="secondary" onClick={selection.cancel}>
              {t('common.cancel')}
            </Button>
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
            <ButtonLink to="/e/$slug/upload" params={{ slug }} variant="secondary">
              {t('photos.addPhotos')}
            </ButtonLink>
            <Button onClick={selection.start} disabled={items.length === 0} data-select>
              {t('photos.select')}
            </Button>
          </>
        )}
      </BottomBar>
      <Outlet />
    </>
  )
}
