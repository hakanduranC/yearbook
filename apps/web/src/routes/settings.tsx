import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link, useRouter } from '@tanstack/react-router'
import { type FormEvent, useEffect, useState } from 'react'
import { Button, ButtonLink } from '~/components/Button'
import { ConfirmSheet } from '~/components/ConfirmSheet'
import { Field, SwitchRow } from '~/components/Field'
import { PageHeader } from '~/components/PageHeader'
import { useToast } from '~/components/Toast'
import { type Locale, locales, useLocale, useT } from '~/i18n'
import type { Me, MeUpdate } from '~/lib/api/types'
import { writeLangCookie } from '~/lib/env'
import { keys } from '~/lib/queries/keys'
import { deleteMyFaceData, logout, meQuery, updateMe } from '~/lib/queries/me'
import styles from '~/styles/pages/form.module.css'

export const Route = createFileRoute('/settings')({
  loader: async ({ context: { queryClient } }) => {
    await queryClient.ensureQueryData(meQuery()).catch(() => undefined)
  },
  component: Settings,
})

const languageLabel: Record<Locale, 'settings.german' | 'settings.english' | 'settings.turkish'> = {
  de: 'settings.german',
  en: 'settings.english',
  tr: 'settings.turkish',
}

function Settings() {
  const t = useT()
  const locale = useLocale()
  const router = useRouter()
  const queryClient = useQueryClient()
  const toast = useToast()
  const me = useQuery(meQuery())
  const [name, setName] = useState(me.data?.display_name ?? '')
  const [birthday, setBirthday] = useState(me.data?.birthdate ?? '')
  const [busy, setBusy] = useState(false)
  const [confirmFaces, setConfirmFaces] = useState(false)

  useEffect(() => {
    if (me.data?.display_name !== undefined) setName(me.data.display_name)
  }, [me.data?.display_name])
  useEffect(() => {
    setBirthday(me.data?.birthdate ?? '')
  }, [me.data?.birthdate])

  const patch = async (body: MeUpdate, optimistic?: Partial<Me>) => {
    const previous = queryClient.getQueryData<Me>(keys.me())
    if (optimistic && previous) queryClient.setQueryData(keys.me(), { ...previous, ...optimistic })
    try {
      const updated = await updateMe(body)
      queryClient.setQueryData(keys.me(), updated)
      return true
    } catch {
      if (previous) queryClient.setQueryData(keys.me(), previous)
      toast(t('common.error'))
      return false
    }
  }

  const saveName = async (ev: FormEvent) => {
    ev.preventDefault()
    setBusy(true)
    if (await patch({ display_name: name.trim() })) toast(t('common.saved'))
    setBusy(false)
  }

  const saveBirthday = async (ev: FormEvent) => {
    ev.preventDefault()
    setBusy(true)
    const ok = await patch(birthday ? { birthdate: birthday } : { clear_birthdate: true })
    if (ok) toast(t('common.saved'))
    setBusy(false)
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
      queryClient.removeQueries({ queryKey: keys.years() })
      router.navigate({ to: '/' })
    }
  }

  const deleteFaces = async () => {
    try {
      await deleteMyFaceData()
      toast(t('settings.faceDataDeleted'))
      queryClient.invalidateQueries({ queryKey: keys.me() })
      queryClient.invalidateQueries({ queryKey: keys.myPeople() })
      queryClient.invalidateQueries({ queryKey: keys.years() })
      queryClient.invalidateQueries({ queryKey: keys.personAll() })
    } catch {
      toast(t('common.error'))
    } finally {
      setConfirmFaces(false)
    }
  }

  return (
    <>
      <PageHeader title={t('settings.title')} back="/" plain />
      <main className={`page page--narrow ${styles.main}`} data-settings>
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('settings.language')}</h2>
          <fieldset
            className={`${styles.segmented} ${styles.segmented3}`}
            aria-label={t('settings.language')}
          >
            {locales.map((l) => (
              <button
                key={l}
                type="button"
                className={styles.segment}
                aria-pressed={locale === l}
                onClick={() => setLanguage(l)}
                data-lang={l}
              >
                {t(languageLabel[l])}
              </button>
            ))}
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
            <form className={styles.section} onSubmit={saveBirthday}>
              <h2 className={styles.sectionTitle}>{t('settings.birthday')}</h2>
              <Field
                label={t('settings.birthday')}
                hint={t('settings.birthdayHint')}
                type="date"
                optional
                value={birthday}
                max={new Date().toISOString().slice(0, 10)}
                onChange={(e) => setBirthday(e.target.value)}
                data-birthday
              />
              <div className={styles.actions}>
                <Button
                  type="submit"
                  variant="secondary"
                  busy={busy}
                  disabled={(me.data.birthdate ?? '') === birthday}
                >
                  {t('common.save')}
                </Button>
                {me.data.birthdate ? (
                  <Button
                    variant="quiet"
                    onClick={async () => {
                      if (await patch({ clear_birthdate: true }, { birthdate: undefined }))
                        toast(t('common.saved'))
                    }}
                  >
                    {t('settings.clearBirthday')}
                  </Button>
                ) : null}
              </div>
            </form>
            <section className={styles.section}>
              <h2 className={styles.sectionTitle}>{t('settings.faces')}</h2>
              <SwitchRow
                label={t('settings.linkAcross')}
                checked={me.data.link_across !== false}
                onChange={(v) => patch({ link_across: v }, { link_across: v })}
              />
              <SwitchRow
                label={t('settings.hideFromPeople')}
                checked={me.data.hide_from_people === true}
                onChange={(v) => patch({ hide_from_people: v }, { hide_from_people: v })}
              />
              <div className={styles.actions}>
                <Button
                  variant="danger"
                  onClick={() => setConfirmFaces(true)}
                  data-delete-face-data
                >
                  {t('settings.deleteFaceData')}
                </Button>
                <Button variant="secondary" disabled title={t('settings.downloadDataSoon')}>
                  {t('settings.downloadData')} · {t('settings.downloadDataSoon')}
                </Button>
              </div>
            </section>
            <section className={styles.section}>
              <h2 className={styles.sectionTitle}>{t('settings.more')}</h2>
              <nav className={styles.linkList}>
                <Link to="/manage">{t('nav.manage')}</Link>
                <Link to="/import">{t('nav.import')}</Link>
                <Link to="/library">{t('nav.library')}</Link>
                <Link to="/people">{t('nav.people')}</Link>
                <Link to="/search/saved">{t('search.savedTitle')}</Link>
              </nav>
            </section>
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
            <ConfirmSheet
              open={confirmFaces}
              title={t('settings.deleteFaceData')}
              body={t('settings.deleteFaceDataBody')}
              confirmLabel={t('common.delete')}
              danger
              onConfirm={deleteFaces}
              onClose={() => setConfirmFaces(false)}
            />
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
