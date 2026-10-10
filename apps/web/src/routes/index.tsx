import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ButtonLink } from '~/components/Button'
import { EventCard } from '~/components/EventCard'
import { useT } from '~/i18n'
import { eventsQuery } from '~/lib/queries/event'
import { meQuery } from '~/lib/queries/me'
import styles from '~/styles/pages/form.module.css'

export const Route = createFileRoute('/')({
  loader: async ({ context: { queryClient } }) => {
    const me = await queryClient
      .ensureQueryData(meQuery())
      .catch(() => ({ authenticated: false as const, locale: 'de' as const }))
    if (me.authenticated) await queryClient.ensureQueryData(eventsQuery()).catch(() => undefined)
  },
  component: Home,
})

function Home() {
  const t = useT()
  const me = useQuery(meQuery())
  const authenticated = me.data?.authenticated === true
  const events = useQuery({ ...eventsQuery(), enabled: authenticated })

  return (
    <main className="page page--narrow">
      <div className={styles.topLinks}>
        <span className={styles.brand}>{t('app.name')}</span>
        <Link
          to="/settings"
          style={{ minHeight: 44, display: 'inline-flex', alignItems: 'center' }}
        >
          {t('nav.settings')}
        </Link>
      </div>
      {authenticated ? (
        <>
          <h1 className={styles.homeTitle}>{t('home.title')}</h1>
          {events.data?.items.length ? (
            <ul className={styles.list}>
              {events.data.items.map((event, i) => (
                <li key={event.id}>
                  <EventCard event={event} variant={i === 0 ? 'hero' : 'list'} />
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.lead}>{t('home.empty')}</p>
          )}
          <div className={styles.actions}>
            <ButtonLink to="/new">{t('home.newEvent')}</ButtonLink>
          </div>
        </>
      ) : (
        <div className={styles.homeHero}>
          <h1 className={styles.homeTitle}>{t('app.tagline')}</h1>
          <p className={styles.lead}>{t('app.intro')}</p>
          <p className={styles.lead} style={{ marginTop: 'var(--s-4)' }}>
            {t('home.signInHint')}
          </p>
          <div className={styles.actions}>
            <ButtonLink to="/login" search={{}}>
              {t('nav.signIn')}
            </ButtonLink>
          </div>
        </div>
      )}
    </main>
  )
}
