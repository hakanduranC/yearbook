import { createFileRoute } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import * as v from 'valibot'
import { Button } from '~/components/Button'
import { Field } from '~/components/Field'
import { PageHeader } from '~/components/PageHeader'
import { useLocale, useT } from '~/i18n'
import { isApiError } from '~/lib/api/client'
import { safeNext } from '~/lib/guards'
import { requestMagicLink } from '~/lib/queries/me'
import styles from '~/styles/pages/form.module.css'

const searchSchema = v.object({ next: v.optional(v.string()) })

export const Route = createFileRoute('/login')({
  validateSearch: searchSchema,
  component: Login,
})

function Login() {
  const t = useT()
  const locale = useLocale()
  const { next } = Route.useSearch()
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const submit = async (ev: FormEvent) => {
    ev.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await requestMagicLink({ email, locale, next: safeNext(next) })
      setSent(email)
    } catch (err) {
      setError(isApiError(err) && err.status === 429 ? t('login.rateLimited') : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader title={t('login.title')} back="/" plain />
      <main className={`page page--narrow ${styles.main}`}>
        {sent ? (
          <>
            <h2 className={styles.title}>{t('login.sentTitle')}</h2>
            <p className={styles.lead}>{t('login.sentBody', { email: sent })}</p>
            {isLocalHost() ? (
              <p className={styles.lead}>
                {t('login.devHint')}{' '}
                <a href="http://localhost:8025" target="_blank" rel="noreferrer">
                  {t('login.devHintLink')}
                </a>
              </p>
            ) : null}
          </>
        ) : (
          <form className={styles.form} onSubmit={submit}>
            <p className={styles.lead}>{t('login.lead')}</p>
            <Field
              label={t('login.email')}
              type="email"
              name="email"
              inputMode="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              error={error}
            />
            <div className={styles.actions}>
              <Button type="submit" busy={busy} disabled={!email}>
                {t('login.submit')}
              </Button>
            </div>
          </form>
        )}
      </main>
    </>
  )
}

/** True when the app runs on a developer machine, where mail goes to Mailpit instead of an inbox. */
function isLocalHost(): boolean {
  if (typeof window === 'undefined') return false
  const h = window.location.hostname
  return (
    h === 'localhost' || h === '127.0.0.1' || h.endsWith('.local') || /^(10|192\.168)\./.test(h)
  )
}
