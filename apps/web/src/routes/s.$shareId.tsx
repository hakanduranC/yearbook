import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { BottomBar } from '~/components/BottomBar'
import { Button } from '~/components/Button'
import { EmptyState } from '~/components/EmptyState'
import { ItemViewer } from '~/components/ItemViewer'
import { MediaTile } from '~/components/MediaTile'
import { SimpleGrid } from '~/components/SimpleGrid'
import { useToast } from '~/components/Toast'
import { type Locale, t as translate, useT } from '~/i18n'
import { isApiError } from '~/lib/api/client'
import { publicOrigin } from '~/lib/env'
import { sharedAlbumQuery } from '~/lib/queries/albums'
import { createZip } from '~/lib/queries/media'
import styles from '~/styles/pages/album.module.css'

export const Route = createFileRoute('/s/$shareId')({
  loader: async ({ context: { queryClient }, params }) => {
    let missing = false
    const album = await queryClient
      .ensureQueryData(sharedAlbumQuery(params.shareId))
      .catch((error: unknown) => {
        missing = isApiError(error) && error.status === 404
        return null
      })
    return {
      missing: missing as boolean,
      origin: publicOrigin(),
      title: album?.title ?? null,
      count: album?.count ?? 0,
      image:
        album?.cover?.large ?? album?.cover?.medium ?? album?.items[0]?.variants?.large ?? null,
    }
  },
  head: ({ loaderData, params, matches }) => {
    if (!loaderData?.title) return {}
    const locale = ((matches[0]?.loaderData as { locale?: Locale } | undefined)?.locale ??
      'de') as Locale
    const url = `${loaderData.origin}/s/${encodeURIComponent(params.shareId)}`
    const description = translate(locale, 'album.ogDescription', { count: loaderData.count })
    return {
      meta: [
        { title: `${loaderData.title} · Yearbook` },
        { name: 'description', content: description },
        { name: 'robots', content: 'noindex' },
        { property: 'og:type', content: 'website' },
        { property: 'og:title', content: loaderData.title },
        { property: 'og:description', content: description },
        { property: 'og:url', content: url },
        { property: 'og:site_name', content: 'Yearbook' },
        ...(loaderData.image
          ? [
              { property: 'og:image', content: loaderData.image },
              { name: 'twitter:card', content: 'summary_large_image' },
              { name: 'twitter:image', content: loaderData.image },
            ]
          : [{ name: 'twitter:card', content: 'summary' }]),
      ],
      links: [{ rel: 'canonical', href: url }],
    }
  },
  component: SharedAlbum,
})

function SharedAlbum() {
  const t = useT()
  const toast = useToast()
  const { shareId } = Route.useParams()
  const { missing } = Route.useLoaderData()
  const album = useQuery({ ...sharedAlbumQuery(shareId), enabled: !missing })
  const [openId, setOpenId] = useState<string | null>(null)
  const [zipping, setZipping] = useState(false)

  if (missing || (album.isError && isApiError(album.error) && album.error.status === 404)) {
    return (
      <main className="page page--narrow">
        <EmptyState kind="not-found" body={t('album.notFound')} />
      </main>
    )
  }
  const data = album.data
  if (!data) {
    return (
      <main className="page page--narrow">
        <p className="muted" style={{ padding: 'var(--s-6) 0' }}>
          {album.isError ? t('common.error') : t('common.loading')}
        </p>
      </main>
    )
  }

  const downloadAll = async () => {
    setZipping(true)
    try {
      const ticket = await createZip(data.items.map((i) => i.id))
      window.location.assign(ticket.url)
    } catch {
      toast(t('common.error'))
    } finally {
      setZipping(false)
    }
  }

  return (
    <>
      <main className={`${styles.main} ${data.allow_download ? 'has-bar' : ''}`} data-shared-album>
        <header className={styles.shareHead}>
          <span className="eyebrow">
            {t('album.readOnly')}
            {data.event_title ? ` · ${t('album.from', { title: data.event_title })}` : ''}
          </span>
          <h1 className={styles.shareTitle}>{data.title}</h1>
          <p className="muted">{t('common.photos', { count: data.count })}</p>
        </header>
        {data.items.length === 0 ? (
          <EmptyState kind="no-photos" body={t('album.empty')} />
        ) : (
          <SimpleGrid>
            {data.items.map((item, i) => (
              <MediaTile
                key={item.id}
                item={item}
                priority={i < 9}
                onOpen={() => setOpenId(item.id)}
              />
            ))}
          </SimpleGrid>
        )}
        {!data.allow_download ? <p className={styles.meta}>{t('album.downloadOff')}</p> : null}
      </main>
      {data.allow_download ? (
        <BottomBar>
          <Button onClick={downloadAll} busy={zipping} data-download-all>
            {t('album.downloadAll')}
          </Button>
        </BottomBar>
      ) : null}
      <ItemViewer
        items={data.items}
        openId={openId}
        title={data.title}
        onClose={() => setOpenId(null)}
        onNavigate={setOpenId}
      />
    </>
  )
}
