import { useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import { Button } from '~/components/Button'
import { Field, SwitchRow } from '~/components/Field'
import { PageHeader } from '~/components/PageHeader'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import type { EventUpdate } from '~/lib/api/types'
import { fromDateTimeLocal, toDateTimeLocal } from '~/lib/format'
import { requireHost } from '~/lib/guards'
import { eventQuery, updateEvent } from '~/lib/queries/event'
import { keys } from '~/lib/queries/keys'
import styles from '~/styles/pages/form.module.css'

export const Route = createFileRoute('/e/$slug/settings')({
  beforeLoad: async ({ context: { queryClient }, params, location }) => {
    await requireHost(queryClient, params.slug, location.href)
  },
  component: EventSettings,
})

function EventSettings() {
  const t = useT()
  const toast = useToast()
  const { slug } = Route.useParams()
  const queryClient = useQueryClient()
  const { data: event } = useSuspenseQuery(eventQuery(slug))
  const [title, setTitle] = useState(event.title)
  const [startsAt, setStartsAt] = useState(toDateTimeLocal(event.starts_at))
  const [location, setLocation] = useState(event.location ?? '')
  const [busy, setBusy] = useState(false)

  const patch = async (body: EventUpdate) => {
    const updated = await updateEvent(slug, body)
    queryClient.setQueryData(keys.event(slug), updated)
    queryClient.invalidateQueries({ queryKey: keys.events() })
    return updated
  }

  const submit = async (ev: FormEvent) => {
    ev.preventDefault()
    setBusy(true)
    try {
      await patch({
        title: title.trim(),
        starts_at: fromDateTimeLocal(startsAt) || event.starts_at,
        location: location.trim() || null,
      })
      toast(t('common.saved'))
    } catch {
      toast(t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const toggle =
    (key: 'guest_upload' | 'guest_view' | 'faces_enabled') => async (value: boolean) => {
      queryClient.setQueryData(keys.event(slug), { ...event, [key]: value })
      try {
        await patch({ [key]: value })
      } catch {
        queryClient.setQueryData(keys.event(slug), event)
        toast(t('common.error'))
      }
    }

  return (
    <>
      <PageHeader title={t('eventSettings.title')} back="/e/$slug" backParams={{ slug }} />
      <main className={`page page--narrow ${styles.main}`}>
        <form className={styles.form} onSubmit={submit}>
          <Field
            label={t('new.name')}
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
            maxLength={200}
            value={location}
            onChange={(e) => setLocation(e.target.value)}
          />
          <div className={styles.actions}>
            <Button type="submit" busy={busy} disabled={!title.trim()}>
              {t('common.save')}
            </Button>
          </div>
        </form>
        <section className={styles.section}>
          <SwitchRow
            label={t('eventSettings.guestUpload')}
            checked={event.guest_upload}
            onChange={toggle('guest_upload')}
          />
          <SwitchRow
            label={t('eventSettings.guestView')}
            checked={event.guest_view}
            onChange={toggle('guest_view')}
          />
          <SwitchRow
            label={t('eventSettings.faces')}
            checked={event.faces_enabled !== false}
            onChange={toggle('faces_enabled')}
          />
        </section>
      </main>
    </>
  )
}
