import { useQueryClient } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import { Button } from '~/components/Button'
import { Field } from '~/components/Field'
import { PageHeader } from '~/components/PageHeader'
import { useT } from '~/i18n'
import { fromDateTimeLocal } from '~/lib/format'
import { requireSession } from '~/lib/guards'
import { createEvent } from '~/lib/queries/event'
import { keys } from '~/lib/queries/keys'
import styles from '~/styles/pages/form.module.css'

export const Route = createFileRoute('/new')({
  beforeLoad: async ({ context: { queryClient }, location }) => {
    await requireSession(queryClient, location.href)
  },
  component: NewEvent,
})

function NewEvent() {
  const t = useT()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [title, setTitle] = useState('')
  const [startsAt, setStartsAt] = useState('')
  const [location, setLocation] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (ev: FormEvent) => {
    ev.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Europe/Berlin'
      const event = await createEvent({
        title: title.trim(),
        starts_at: fromDateTimeLocal(startsAt),
        timezone,
        ...(location.trim() ? { location: location.trim() } : {}),
      })
      queryClient.setQueryData(keys.event(event.slug), event)
      queryClient.invalidateQueries({ queryKey: keys.events() })
      navigate({ to: '/e/$slug/share', params: { slug: event.slug } })
    } catch {
      setError(t('common.error'))
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader title={t('new.title')} back="/" plain />
      <main className={`page page--narrow ${styles.main}`}>
        <form className={styles.form} onSubmit={submit}>
          <Field
            label={t('new.name')}
            placeholder={t('new.namePlaceholder')}
            required
            maxLength={120}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <Field
            label={t('new.date')}
            type="datetime-local"
            required
            value={startsAt}
            onChange={(e) => setStartsAt(e.target.value)}
          />
          <Field
            label={t('new.location')}
            optional
            placeholder={t('new.locationPlaceholder')}
            maxLength={200}
            value={location}
            onChange={(e) => setLocation(e.target.value)}
          />
          {error ? <p className={styles.error}>{error}</p> : null}
          <div className={styles.actions}>
            <Button type="submit" busy={busy} disabled={!title.trim() || !startsAt}>
              {t('new.create')}
            </Button>
          </div>
        </form>
      </main>
    </>
  )
}
