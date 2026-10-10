import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, notFound, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { BottomBar } from '~/components/BottomBar'
import { Button } from '~/components/Button'
import { ConfirmSheet } from '~/components/ConfirmSheet'
import { EmptyState } from '~/components/EmptyState'
import { Field } from '~/components/Field'
import { ItemViewer } from '~/components/ItemViewer'
import { MediaTile } from '~/components/MediaTile'
import { PageHeader } from '~/components/PageHeader'
import { ShareSheet } from '~/components/ShareSheet'
import { Sheet } from '~/components/Sheet'
import { SimpleGrid } from '~/components/SimpleGrid'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import { isApiError } from '~/lib/api/client'
import { albumQuery, deleteAlbum, updateAlbum } from '~/lib/queries/albums'
import { keys } from '~/lib/queries/keys'
import { createZip } from '~/lib/queries/media'
import { useSelection } from '~/lib/selection'
import styles from '~/styles/pages/album.module.css'

export const Route = createFileRoute('/albums/$albumId')({
  loader: async ({ context: { queryClient }, params }) => {
    try {
      await queryClient.ensureQueryData(albumQuery(params.albumId))
    } catch (error) {
      if (isApiError(error) && error.status === 404) throw notFound()
    }
  },
  component: AlbumPage,
})

function AlbumPage() {
  const t = useT()
  const toast = useToast()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { albumId } = Route.useParams()
  const album = useQuery(albumQuery(albumId))
  const selection = useSelection()
  const [openId, setOpenId] = useState<string | null>(null)
  const [renaming, setRenaming] = useState(false)
  const [title, setTitle] = useState('')
  const [sharing, setSharing] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [zipping, setZipping] = useState(false)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: keys.album(albumId) })
    if (album.data?.event_slug)
      queryClient.invalidateQueries({ queryKey: keys.albums(album.data.event_slug) })
  }

  const rename = useMutation({
    mutationFn: (next: string) => updateAlbum(albumId, { title: next }),
    onSuccess: (detail) => {
      queryClient.setQueryData(keys.album(albumId), detail)
      invalidate()
      setRenaming(false)
      toast(t('album.renamed'))
    },
    onError: () => toast(t('common.error')),
  })
  const removeItems = useMutation({
    mutationFn: (ids: string[]) => updateAlbum(albumId, { remove: ids }),
    onSuccess: (detail, ids) => {
      queryClient.setQueryData(keys.album(albumId), detail)
      invalidate()
      selection.cancel()
      setConfirmRemove(false)
      toast(t('album.removed', { count: ids.length }))
    },
    onError: () => toast(t('common.error')),
  })
  const destroy = useMutation({
    mutationFn: () => deleteAlbum(albumId),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: keys.album(albumId) })
      invalidate()
      toast(t('album.deleted'))
      navigate({ to: '/manage' })
    },
    onError: () => toast(t('common.error')),
  })

  const downloadAll = async () => {
    if (!album.data?.items.length) return
    setZipping(true)
    try {
      const ticket = await createZip(album.data.items.map((i) => i.id))
      window.location.assign(ticket.url)
    } catch {
      toast(t('common.error'))
    } finally {
      setZipping(false)
    }
  }

  if (album.isError && isApiError(album.error) && album.error.status === 404) {
    return (
      <main className="page page--narrow">
        <EmptyState kind="not-found" body={t('album.notFound')} />
      </main>
    )
  }
  const data = album.data
  const canEdit = data?.can_edit === true

  return (
    <>
      <PageHeader
        title={data?.title ?? t('common.loading')}
        back="history"
        right={
          canEdit ? (
            <Button
              variant="quiet"
              small
              onClick={() => {
                setTitle(data.title)
                setRenaming(true)
              }}
              data-rename
            >
              {t('common.rename')}
            </Button>
          ) : null
        }
      />
      <main className={`${styles.main} has-bar`} data-album-page={albumId}>
        {data ? (
          <header className={styles.head}>
            <span className="eyebrow">
              {t(`album.kind.${data.kind}`)}
              {data.event_title ? ` · ${t('album.from', { title: data.event_title })}` : ''}
            </span>
            <p className={styles.meta}>{t('common.photos', { count: data.count })}</p>
          </header>
        ) : null}
        {data && data.items.length === 0 ? (
          <EmptyState kind="no-photos" body={t('album.empty')} />
        ) : data ? (
          <SimpleGrid>
            {data.items.map((item, i) => (
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
        ) : null}
      </main>
      <BottomBar>
        {selection.active ? (
          <>
            <Button variant="secondary" onClick={selection.cancel}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="danger"
              disabled={selection.selected.size === 0}
              onClick={() => setConfirmRemove(true)}
              data-remove-selected
            >
              {t('album.removeN', { count: selection.selected.size })}
            </Button>
          </>
        ) : (
          <>
            {canEdit ? (
              <Button variant="secondary" onClick={selection.start} data-select>
                {t('album.removeItems')}
              </Button>
            ) : (
              <Button variant="secondary" onClick={downloadAll} busy={zipping}>
                {t('album.downloadAll')}
              </Button>
            )}
            <Button onClick={() => setSharing(true)} data-share-album>
              {t('common.share')}
            </Button>
            {canEdit ? (
              <Button variant="danger" onClick={() => setConfirmDelete(true)} data-delete-album>
                {t('album.delete')}
              </Button>
            ) : null}
          </>
        )}
      </BottomBar>
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
            data-album-title
          />
          <Button type="submit" busy={rename.isPending} disabled={!title.trim()}>
            {t('common.save')}
          </Button>
        </form>
      </Sheet>
      <ShareSheet
        open={sharing}
        albumId={albumId}
        title={t('album.shareTitle')}
        onClose={() => setSharing(false)}
      />
      <ConfirmSheet
        open={confirmRemove}
        title={t('album.removeN', { count: selection.selected.size })}
        confirmLabel={t('common.remove')}
        danger
        busy={removeItems.isPending}
        onConfirm={() => removeItems.mutate([...selection.selected])}
        onClose={() => setConfirmRemove(false)}
      />
      <ConfirmSheet
        open={confirmDelete}
        title={t('album.delete')}
        body={t('album.deleteBody')}
        confirmLabel={t('common.delete')}
        danger
        busy={destroy.isPending}
        onConfirm={() => destroy.mutate()}
        onClose={() => setConfirmDelete(false)}
      />
      {data ? (
        <ItemViewer
          items={data.items}
          openId={openId}
          title={data.title}
          onClose={() => setOpenId(null)}
          onNavigate={setOpenId}
        />
      ) : null}
    </>
  )
}
