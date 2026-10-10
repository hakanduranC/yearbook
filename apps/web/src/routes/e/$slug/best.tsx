import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { BottomBar } from '~/components/BottomBar'
import { Button, ButtonLink } from '~/components/Button'
import { EmptyState } from '~/components/EmptyState'
import { MediaTile } from '~/components/MediaTile'
import { PageHeader } from '~/components/PageHeader'
import { ShareSheet } from '~/components/ShareSheet'
import { SimpleGrid } from '~/components/SimpleGrid'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import { loadEvent } from '~/lib/guards'
import {
  albumQuery,
  albumsQuery,
  createAlbum,
  highlightsAlbum,
  updateAlbum,
} from '~/lib/queries/albums'
import { eventQuery, isHost } from '~/lib/queries/event'
import { keys } from '~/lib/queries/keys'
import { highlightsQuery } from '~/lib/queries/media'
import styles from '~/styles/pages/album.module.css'

export const Route = createFileRoute('/e/$slug/best')({
  loader: async ({ context: { queryClient }, params }) => {
    await loadEvent(queryClient, params.slug)
    await queryClient.ensureQueryData(highlightsQuery(params.slug)).catch(() => undefined)
  },
  component: Highlights,
})

function Highlights() {
  const t = useT()
  const toast = useToast()
  const queryClient = useQueryClient()
  const { slug } = Route.useParams()
  const { data: event } = useSuspenseQuery(eventQuery(slug))
  const host = isHost(event)
  const best = useQuery(highlightsQuery(slug))
  const albums = useQuery(albumsQuery(slug))
  const album = highlightsAlbum(albums.data, t('best.albumTitle'))
  // The album list carries counts only; membership comes from its detail, loaded once we know the id.
  const detail = useQuery({ ...albumQuery(album?.id ?? ''), enabled: album !== null })
  const pinned = new Set(detail.data?.items.map((i) => i.id) ?? [])
  const [sharing, setSharing] = useState(false)

  const pin = useMutation({
    mutationFn: async ({ id, on }: { id: string; on: boolean }) => {
      if (!album) {
        return createAlbum({ event_slug: slug, title: t('best.albumTitle'), media_ids: [id] })
      }
      return updateAlbum(album.id, on ? { add: [id] } : { remove: [id] })
    },
    onSuccess: (_result, { on }) => {
      queryClient.invalidateQueries({ queryKey: keys.albums(slug) })
      if (album) queryClient.invalidateQueries({ queryKey: keys.album(album.id) })
      toast(on ? t('best.pinned') : t('common.remove'))
    },
    onError: () => toast(t('common.error')),
  })

  const items = best.data?.items ?? []

  return (
    <>
      <PageHeader title={t('best.title')} back="/e/$slug/photos" backParams={{ slug }} />
      <main className={`${styles.main} has-bar`} data-best>
        {album ? <p className={styles.meta}>{t('best.inAlbum', { count: album.count })}</p> : null}
        {best.isError && !best.data ? (
          <EmptyState kind="offline" />
        ) : best.isSuccess && items.length === 0 ? (
          <EmptyState kind="no-highlights" />
        ) : (
          <SimpleGrid columns={2}>
            {items.map((item, i) => (
              <MediaTile
                key={item.id}
                item={item}
                aspect="4:3"
                priority={i < 4}
                link={{
                  to: '/e/$slug/photos/$photoId',
                  params: { slug, photoId: item.id },
                  search: { filter: 'best' },
                }}
                action={
                  host ? (
                    <button
                      type="button"
                      aria-pressed={pinned.has(item.id)}
                      aria-label={pinned.has(item.id) ? t('best.unpin') : t('best.pin')}
                      onClick={() => pin.mutate({ id: item.id, on: !pinned.has(item.id) })}
                      data-pin={item.id}
                    >
                      {pinned.has(item.id) ? t('best.unpin') : t('best.pin')}
                    </button>
                  ) : undefined
                }
              />
            ))}
          </SimpleGrid>
        )}
      </main>
      <BottomBar>
        {album ? (
          <ButtonLink to="/albums/$albumId" params={{ albumId: album.id }} variant="secondary">
            {t('common.open')}
          </ButtonLink>
        ) : null}
        <Button onClick={() => setSharing(true)} disabled={!album} data-share-highlights>
          {t('best.shareHighlights')}
        </Button>
      </BottomBar>
      <ShareSheet
        open={sharing}
        albumId={album?.id ?? null}
        title={t('best.shareHighlights')}
        onClose={() => setSharing(false)}
      />
    </>
  )
}
