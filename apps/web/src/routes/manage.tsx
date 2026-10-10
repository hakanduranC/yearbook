import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useState } from 'react'
import { AlbumCard } from '~/components/AlbumCard'
import { BottomBar } from '~/components/BottomBar'
import { Button, ButtonLink } from '~/components/Button'
import { ConfirmSheet } from '~/components/ConfirmSheet'
import { Field } from '~/components/Field'
import { PageHeader } from '~/components/PageHeader'
import { Sheet } from '~/components/Sheet'
import { useToast } from '~/components/Toast'
import { useLocale, useT } from '~/i18n'
import type { Album, Event } from '~/lib/api/types'
import { formatEventDate } from '~/lib/format'
import { requireSession } from '~/lib/guards'
import { albumsQuery, deleteAlbum, shareAlbum, updateAlbum } from '~/lib/queries/albums'
import { deleteEvent, eventsQuery, isHost } from '~/lib/queries/event'
import { keys } from '~/lib/queries/keys'
import styles from '~/styles/pages/manage.module.css'

export const Route = createFileRoute('/manage')({
  beforeLoad: async ({ context: { queryClient }, location }) => {
    await requireSession(queryClient, location.href)
  },
  loader: async ({ context: { queryClient } }) => {
    await queryClient.ensureQueryData(eventsQuery()).catch(() => undefined)
  },
  component: ManagePage,
})

function ManagePage() {
  const t = useT()
  const events = useQuery(eventsQuery())
  const hosted = (events.data?.items ?? []).filter((e) => isHost(e))

  return (
    <>
      <PageHeader title={t('manage.title')} back="/" />
      <main className={`page ${styles.main} has-bar`} data-manage>
        <p className={styles.lead}>{t('manage.lead')}</p>
        {events.isSuccess && hosted.length === 0 ? (
          <p className={styles.lead}>{t('manage.empty')}</p>
        ) : null}
        <ul className={styles.list}>
          {hosted.map((event) => (
            <li key={event.id}>
              <EventPanel event={event} />
            </li>
          ))}
        </ul>
        <section className={styles.importBox}>
          <h2 className={styles.importTitle}>{t('manage.import')}</h2>
          <p className={styles.lead}>{t('manage.importLead')}</p>
          <ButtonLink to="/import" variant="secondary" data-go-import>
            {t('nav.import')}
          </ButtonLink>
        </section>
      </main>
      <BottomBar>
        <ButtonLink to="/import" variant="secondary">
          {t('nav.import')}
        </ButtonLink>
        <ButtonLink to="/new">{t('home.newEvent')}</ButtonLink>
      </BottomBar>
    </>
  )
}

function EventPanel({ event }: { event: Event }) {
  const t = useT()
  const locale = useLocale()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const albums = useQuery(albumsQuery(event.slug))
  const remove = useMutation({
    mutationFn: () => deleteEvent(event.slug),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: keys.eventAll(event.slug) })
      queryClient.invalidateQueries({ queryKey: keys.events() })
      queryClient.invalidateQueries({ queryKey: keys.years() })
      toast(t('manage.deleted'))
    },
    onError: () => toast(t('common.error')),
    onSettled: () => setConfirmDelete(false),
  })
  const c = event.counts
  const status =
    c.processing > 0
      ? t('manage.processing', { count: c.processing })
      : c.failed > 0
        ? t('manage.failed', { count: c.failed })
        : t('manage.processed')

  return (
    <article className={styles.event} data-manage-event={event.slug}>
      <div className={styles.eventHead}>
        {event.cover?.thumb ? (
          <img
            className={styles.cover}
            src={event.cover.small ?? event.cover.thumb}
            alt=""
            loading="lazy"
          />
        ) : (
          <span className={styles.cover} />
        )}
        <div className={styles.eventText}>
          <Link to="/e/$slug" params={{ slug: event.slug }} className={styles.eventTitle}>
            {event.title}
          </Link>
          <span className={styles.meta}>
            {formatEventDate(event.starts_at, locale, event.timezone)} ·{' '}
            {t('common.photos', { count: c.photos })} · {t('common.videos', { count: c.videos })}
          </span>
          <span
            className={[styles.meta, c.failed > 0 ? styles.failed : null].filter(Boolean).join(' ')}
          >
            {status}
            {c.people ? ` · ${t('common.people', { count: c.people })}` : ''}
          </span>
        </div>
      </div>
      <nav className={styles.quick} aria-label={event.title}>
        <Link to="/e/$slug/share" params={{ slug: event.slug }} className={styles.quickLink}>
          {t('manage.share')}
        </Link>
        <Link to="/e/$slug/uploads" params={{ slug: event.slug }} className={styles.quickLink}>
          {t('manage.uploads')}
        </Link>
        <Link
          to="/e/$slug/people/manage"
          params={{ slug: event.slug }}
          className={styles.quickLink}
        >
          {t('manage.people')}
        </Link>
        <Link to="/e/$slug/settings" params={{ slug: event.slug }} className={styles.quickLink}>
          {t('manage.settings')}
        </Link>
        <Link to="/e/$slug/best" params={{ slug: event.slug }} className={styles.quickLink}>
          {t('manage.highlights')}
        </Link>
        <button
          type="button"
          className={`${styles.quickLink} ${styles.quickDanger}`}
          onClick={() => setConfirmDelete(true)}
          data-delete-event
        >
          {t('manage.deleteEvent')}
        </button>
      </nav>
      <section className={styles.albums}>
        <h3 className="eyebrow">{t('manage.albums')}</h3>
        {albums.isSuccess && albums.data.length === 0 ? (
          <p className={styles.meta}>{t('manage.noAlbums')}</p>
        ) : null}
        {(albums.data ?? []).map((album) => (
          <AlbumRow key={album.id} album={album} slug={event.slug} />
        ))}
      </section>
      <ConfirmSheet
        open={confirmDelete}
        title={t('manage.deleteEventTitle', { title: event.title })}
        body={t('manage.deleteEventBody')}
        confirmLabel={t('manage.deleteEvent')}
        danger
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
        onClose={() => setConfirmDelete(false)}
      />
    </article>
  )
}

function AlbumRow({ album, slug }: { album: Album; slug: string }) {
  const t = useT()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [renaming, setRenaming] = useState(false)
  const [title, setTitle] = useState(album.title)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: keys.albums(slug) })
    queryClient.invalidateQueries({ queryKey: keys.album(album.id) })
  }
  const rename = useMutation({
    mutationFn: (next: string) => updateAlbum(album.id, { title: next }),
    onSuccess: () => {
      refresh()
      setRenaming(false)
      toast(t('album.renamed'))
    },
    onError: () => toast(t('common.error')),
  })
  const remove = useMutation({
    mutationFn: () => deleteAlbum(album.id),
    onSuccess: () => {
      refresh()
      toast(t('album.deleted'))
    },
    onError: () => toast(t('common.error')),
    onSettled: () => setConfirmDelete(false),
  })
  const copyLink = async () => {
    try {
      const share = await shareAlbum(album.id, true)
      await navigator.clipboard.writeText(share.url)
      toast(t('common.copied'))
    } catch {
      toast(t('common.error'))
    }
  }

  return (
    <>
      <AlbumCard
        album={album}
        actions={
          <>
            <ButtonLink
              to="/albums/$albumId"
              params={{ albumId: album.id }}
              variant="secondary"
              small
            >
              {t('common.open')}
            </ButtonLink>
            {album.can_edit !== false ? (
              <>
                <Button variant="quiet" small onClick={() => setRenaming(true)} data-rename-album>
                  {t('common.rename')}
                </Button>
                <Button variant="quiet" small onClick={copyLink} data-copy-album-link>
                  {t('common.copy')}
                </Button>
                <Button
                  variant="quiet"
                  small
                  onClick={() => setConfirmDelete(true)}
                  data-delete-album
                >
                  {t('common.delete')}
                </Button>
              </>
            ) : null}
          </>
        }
      />
      <Sheet open={renaming} onClose={() => setRenaming(false)} title={t('common.rename')}>
        <form
          className={styles.form}
          onSubmit={(ev) => {
            ev.preventDefault()
            if (title.trim()) rename.mutate(title.trim())
          }}
        >
          <Field
            label={t('album.newName')}
            value={title}
            maxLength={120}
            required
            onChange={(e) => setTitle(e.target.value)}
          />
          <Button type="submit" busy={rename.isPending} disabled={!title.trim()}>
            {t('common.save')}
          </Button>
        </form>
      </Sheet>
      <ConfirmSheet
        open={confirmDelete}
        title={t('album.delete')}
        body={t('album.deleteBody')}
        confirmLabel={t('common.delete')}
        danger
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
        onClose={() => setConfirmDelete(false)}
      />
    </>
  )
}
