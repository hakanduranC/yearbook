import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import { BottomBar } from '~/components/BottomBar'
import { Button } from '~/components/Button'
import { EmptyState } from '~/components/EmptyState'
import { ItemViewer } from '~/components/ItemViewer'
import { MediaTile } from '~/components/MediaTile'
import { PageHeader } from '~/components/PageHeader'
import { Sheet } from '~/components/Sheet'
import { SimpleGrid } from '~/components/SimpleGrid'
import { useToast } from '~/components/Toast'
import { useLocale, useT } from '~/i18n'
import type { MediaPage } from '~/lib/api/types'
import { formatEventDate } from '~/lib/format'
import { flattenPages } from '~/lib/grouping'
import { requireSession } from '~/lib/guards'
import { eventsQuery } from '~/lib/queries/event'
import { assignMediaEvent, libraryQuery } from '~/lib/queries/imports'
import { keys } from '~/lib/queries/keys'
import { useSelection } from '~/lib/selection'
import styles from '~/styles/pages/album.module.css'

export const Route = createFileRoute('/library')({
  beforeLoad: async ({ context: { queryClient }, location }) => {
    await requireSession(queryClient, location.href)
  },
  loader: async ({ context: { queryClient } }) => {
    await Promise.all([
      queryClient.ensureInfiniteQueryData(libraryQuery(true)).catch(() => undefined),
      queryClient.ensureQueryData(eventsQuery()).catch(() => undefined),
    ])
  },
  component: LibraryPage,
})

function LibraryPage() {
  const t = useT()
  const locale = useLocale()
  const toast = useToast()
  const queryClient = useQueryClient()
  const library = useInfiniteQuery(libraryQuery(true))
  const events = useQuery(eventsQuery())
  const selection = useSelection()
  const [openId, setOpenId] = useState<string | null>(null)
  const [picking, setPicking] = useState(false)
  const sentinel = useRef<HTMLDivElement>(null)
  const { items } = flattenPages(library.data?.pages)

  useEffect(() => {
    const el = sentinel.current
    if (!el || !library.hasNextPage) return
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting) && !library.isFetchingNextPage)
        library.fetchNextPage()
    })
    io.observe(el)
    return () => io.disconnect()
  }, [library.hasNextPage, library.isFetchingNextPage, library.fetchNextPage])

  const move = useMutation({
    mutationFn: async ({ ids, slug }: { ids: string[]; slug: string }) => {
      const results = await Promise.allSettled(ids.map((id) => assignMediaEvent(id, slug)))
      const moved = ids.filter((_, i) => results[i]?.status === 'fulfilled')
      if (moved.length === 0) throw new Error('move failed')
      return { moved, slug }
    },
    onSuccess: ({ moved, slug }) => {
      const gone = new Set(moved)
      queryClient.setQueryData<{ pages: MediaPage[]; pageParams: unknown[] }>(
        keys.library(true),
        (old) =>
          old
            ? {
                ...old,
                pages: old.pages.map((p) => ({
                  ...p,
                  items: p.items.filter((i) => !gone.has(i.id)),
                })),
              }
            : old,
      )
      queryClient.invalidateQueries({ queryKey: keys.libraryAll() })
      queryClient.invalidateQueries({ queryKey: keys.eventAll(slug) })
      queryClient.invalidateQueries({ queryKey: keys.events() })
      toast(t('library.moved', { count: moved.length }))
      selection.cancel()
      setPicking(false)
    },
    onError: () => toast(t('common.error')),
  })

  return (
    <>
      <PageHeader title={t('library.title')} back="/import" />
      <main className={`${styles.main} has-bar`} data-library>
        <p className={styles.meta}>{t('library.lead')}</p>
        {library.isSuccess && items.length === 0 ? (
          <EmptyState kind="library" />
        ) : (
          <SimpleGrid>
            {items.map((item, i) => (
              <MediaTile
                key={item.id}
                item={item}
                priority={i < 9}
                selectMode={selection.active}
                selected={selection.selected.has(item.id)}
                onToggle={selection.toggle}
                onOpen={() => setOpenId(item.id)}
              />
            ))}
          </SimpleGrid>
        )}
        <div ref={sentinel} />
      </main>
      <BottomBar>
        {selection.active ? (
          <>
            <Button variant="secondary" onClick={selection.cancel}>
              {t('common.cancel')}
            </Button>
            <Button
              disabled={selection.selected.size === 0}
              onClick={() => setPicking(true)}
              data-move
            >
              {t('library.moveN', { count: selection.selected.size })}
            </Button>
          </>
        ) : (
          <Button
            variant="secondary"
            onClick={selection.start}
            disabled={items.length === 0}
            data-select
          >
            {t('photos.select')}
          </Button>
        )}
      </BottomBar>
      <Sheet open={picking} onClose={() => setPicking(false)} title={t('library.pickEvent')}>
        <ul className={styles.pickList} data-pick-event>
          {(events.data?.items ?? []).map((e) => (
            <li key={e.id}>
              <button
                type="button"
                className={styles.pickRow}
                disabled={move.isPending}
                onClick={() => move.mutate({ ids: [...selection.selected], slug: e.slug })}
                data-pick-slug={e.slug}
              >
                <span className={styles.pickTitle}>{e.title}</span>
                <span className={styles.meta}>
                  {formatEventDate(e.starts_at, locale, e.timezone)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Sheet>
      <ItemViewer
        items={items}
        openId={openId}
        title={t('library.title')}
        onClose={() => setOpenId(null)}
        onNavigate={setOpenId}
      />
    </>
  )
}
