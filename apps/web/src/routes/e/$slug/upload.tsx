import { useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { type ChangeEvent, type FormEvent, useEffect, useRef, useState } from 'react'
import { BottomBar } from '~/components/BottomBar'
import { Button, ButtonLink } from '~/components/Button'
import { Field } from '~/components/Field'
import { PageHeader } from '~/components/PageHeader'
import { Sheet } from '~/components/Sheet'
import { UploadList } from '~/components/UploadList'
import { useT } from '~/i18n'
import { eventQuery, isHost, updateGuest } from '~/lib/queries/event'
import { keys } from '~/lib/queries/keys'
import { counts, itemsOf } from '~/lib/upload/machine'
import { useUploader } from '~/lib/upload/useUploader'
import styles from '~/styles/pages/upload.module.css'

const ACCEPT = 'image/*,video/*,.heic,.heif,.mov,.mp4'

export const Route = createFileRoute('/e/$slug/upload')({
  component: UploadPage,
})

function UploadPage() {
  const t = useT()
  const { slug } = Route.useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: event } = useSuspenseQuery(eventQuery(slug))
  const anonymous = event.viewer.role === 'anonymous'
  const uploader = useUploader(slug, anonymous)
  const inputRef = useRef<HTMLInputElement>(null)
  const items = itemsOf(uploader.state)
  const summary = counts(uploader.state)
  const running = uploader.state.queue === 'running' || uploader.state.queue === 'draining'
  const canUpload = event.guest_upload || isHost(event)

  const [sheetOpen, setSheetOpen] = useState(false)
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  const askedRef = useRef(false)

  // Show the name sheet once when the queue finishes and the viewer has no name yet.
  useEffect(() => {
    if (!uploader.state.finishedAt || askedRef.current) return
    if (summary.succeeded === 0) return
    if (event.viewer.display_name) return
    askedRef.current = true
    setSheetOpen(true)
  }, [uploader.state.finishedAt, summary.succeeded, event.viewer.display_name])

  const onPick = (ev: ChangeEvent<HTMLInputElement>) => {
    // iOS replaces the FileList on every pick: copy the refs out immediately.
    const files = ev.target.files ? Array.from(ev.target.files) : []
    if (files.length) uploader.addFiles(files)
    ev.target.value = ''
  }

  const saveName = async (ev: FormEvent) => {
    ev.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      await updateGuest(slug, name.trim())
      await queryClient.invalidateQueries({ queryKey: keys.event(slug) })
      setSheetOpen(false)
      uploader.acknowledgeFinished()
      navigate({ to: '/e/$slug/photos', params: { slug }, search: {} })
    } catch {
      setSaving(false)
    }
  }

  const skip = () => {
    setSheetOpen(false)
    uploader.acknowledgeFinished()
    navigate({ to: '/e/$slug/photos', params: { slug }, search: {} })
  }

  return (
    <>
      <PageHeader
        title={t('upload.title', { title: event.title })}
        back="/e/$slug"
        backParams={{ slug }}
      />
      <main className={`page page--narrow ${styles.main}`} data-upload-page>
        <input
          ref={inputRef}
          className={styles.input}
          type="file"
          multiple
          accept={ACCEPT}
          onChange={onPick}
          data-testid="file-input"
          tabIndex={-1}
        />
        {!canUpload ? <p className={styles.summary}>{t('upload.closed')}</p> : null}
        {uploader.resumable > 0 ? (
          <div className={styles.resume} data-resume>
            <span className={styles.resumeHint}>{t('upload.resumeHint')}</span>
            <div className={styles.resumeActions}>
              <Button variant="secondary" onClick={() => uploader.resume()}>
                {t('upload.resume', { count: uploader.resumable })}
              </Button>
              <Button variant="quiet" onClick={() => uploader.discardResumable()}>
                {t('upload.discard')}
              </Button>
            </div>
          </div>
        ) : null}
        {items.length === 0 ? (
          <div className={styles.empty}>
            <p className={styles.emptyLead}>{t('upload.emptyLead')}</p>
            <p className={styles.emptySub}>{t('upload.emptySub')}</p>
          </div>
        ) : (
          <>
            <p className={styles.summary} role="status" data-upload-summary>
              {!uploader.state.online
                ? t('common.offline')
                : running
                  ? t('upload.progressRunning', { done: summary.done, total: summary.total })
                  : t('upload.progress', { done: summary.done, total: summary.total })}
            </p>
            <UploadList items={items} onRetry={uploader.retry} onCancel={uploader.cancel} />
          </>
        )}
      </main>
      <BottomBar>
        {items.length > 0 ? (
          <ButtonLink to="/e/$slug/photos" params={{ slug }} search={{}} variant="secondary">
            {t('upload.seePhotos')}
          </ButtonLink>
        ) : null}
        <Button onClick={() => inputRef.current?.click()} disabled={!canUpload} data-testid="pick">
          {items.length ? t('upload.pickMore') : t('upload.pick')}
        </Button>
      </BottomBar>
      <Sheet open={sheetOpen} onClose={skip} title={t('name.title')} body={t('name.body')}>
        <form className={styles.sheetForm} onSubmit={saveName} data-name-sheet>
          <Field
            label={t('name.field')}
            autoComplete="name"
            maxLength={80}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
          <Button type="submit" busy={saving} disabled={!name.trim()}>
            {t('name.submit')}
          </Button>
          <Link
            to="/e/$slug/photos"
            params={{ slug }}
            search={{}}
            className={styles.skip}
            onClick={skip}
          >
            {t('name.skip')}
          </Link>
        </form>
      </Sheet>
    </>
  )
}
