import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, useRouter } from '@tanstack/react-router'
import { type FormEvent, useEffect, useState } from 'react'
import { Button, ButtonLink } from '~/components/Button'
import { Field } from '~/components/Field'
import { PageHeader } from '~/components/PageHeader'
import { useToast } from '~/components/Toast'
import { type Locale, useLocale, useT } from '~/i18n'
import { writeLangCookie } from '~/lib/env'
import { keys } from '~/lib/queries/keys'
import { logout, meQuery, updateMe } from '~/lib/queries/me'
import styles from '~/styles/pages/form.module.css'

export const Route = createFileRoute('/settings')({
  loader: async ({ context: { queryClient } }) => {
    await queryClient.ensureQueryData(meQuery()).catch(() => undefined)
  },
  component: Settings,
})

function Settings() {
  const t = useT()
  const locale = useLocale()
  const router = useRouter()
  const queryClient = useQueryClient()
  const toast = useToast()
  const me = useQuery(meQuery())
  const [name, setName] = useState(me.data?.display_name ?? '')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (me.data?.display_name !== undefined) setName(me.data.display_name)
  }, [me.data?.display_name])

  const saveName = async (ev: FormEvent) => {
    ev.preventDefault()
    setBusy(true)
    try {
      const updated = await updateMe({ display_name: name.trim() })
      queryClient.setQueryData(keys.me(), updated)
      toast(t('common.saved'))
    } catch {
      toast(t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const setLanguage = async (next: Locale) => {
    writeLangCookie(next)
    if (me.data?.authenticated) {
      updateMe({ locale: next })
        .then((updated) => queryClient.setQueryData(keys.me(), updated))
        .catch(() => {})
    }
    await router.invalidate()
  }

  const signOut = async () => {
    try {
      await logout()
    } finally {
      queryClient.setQueryData(keys.me(), { authenticated: false, locale })
      queryClient.removeQueries({ queryKey: keys.events() })
      router.navigate({ to: '/' })
    }
  }

  return (
    <>
      <PageHeader title={t('settings.title')} back="/" plain />
      <main className={`page page--narrow ${styles.main}`}>
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('settings.language')}</h2>
          <fieldset className={styles.segmented} aria-label={t('settings.language')}>
            <button
              type="button"
              className={styles.segment}
              aria-pressed={locale === 'de'}
              onClick={() => setLanguage('de')}
            >
              {t('settings.german')}
            </button>
            <button
              type="button"
              className={styles.segment}
              aria-pressed={locale === 'en'}
              onClick={() => setLanguage('en')}
            >
              {t('settings.english')}
            </button>
          </fieldset>
        </section>
        {me.data?.authenticated ? (
          <>
            <form className={styles.section} onSubmit={saveName}>
              <h2 className={styles.sectionTitle}>{t('settings.name')}</h2>
              <Field
                label={t('settings.name')}
                hint={t('settings.nameHint')}
                value={name}
                maxLength={80}
                onChange={(e) => setName(e.target.value)}
              />
              <div className={styles.actions}>
                <Button type="submit" variant="secondary" busy={busy} disabled={!name.trim()}>
                  {t('common.save')}
                </Button>
              </div>
            </form>
            <section className={styles.section}>
              <h2 className={styles.sectionTitle}>{t('settings.account')}</h2>
              <p className={styles.lead}>
                {t('settings.signedInAs', { email: me.data.email ?? '' })}
              </p>
              <div className={styles.actions}>
                <Button variant="secondary" onClick={signOut}>
                  {t('nav.signOut')}
                </Button>
              </div>
            </section>
          </>
        ) : (
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t('settings.account')}</h2>
            <p className={styles.lead}>{t('settings.notSignedIn')}</p>
            <div className={styles.actions}>
              <ButtonLink to="/login" search={{}} variant="secondary">
                {t('nav.signIn')}
              </ButtonLink>
            </div>
          </section>
        )}
      </main>
    </>
  )
}
