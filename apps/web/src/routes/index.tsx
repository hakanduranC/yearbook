import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { BottomBar } from '~/components/BottomBar'
import { ButtonLink } from '~/components/Button'
import { FanStack } from '~/components/FanStack'
import { Suggestions } from '~/components/Suggestions'
import { useLocale, useT } from '~/i18n'
import { formatEventDate } from '~/lib/format'
import { homeRows } from '~/lib/home'
import { eventsQuery } from '~/lib/queries/event'
import { meQuery } from '~/lib/queries/me'
import { yearsQuery } from '~/lib/queries/yearbook'
import formStyles from '~/styles/pages/form.module.css'
import styles from '~/styles/pages/home.module.css'

export const Route = createFileRoute('/')({
  loader: async ({ context: { queryClient } }) => {
    const me = await queryClient
      .ensureQueryData(meQuery())
      .catch(() => ({ authenticated: false as const, locale: 'de' as const }))
    if (me.authenticated) {
      await Promise.all([
        queryClient.ensureQueryData(yearsQuery()).catch(() => undefined),
        queryClient.ensureQueryData(eventsQuery()).catch(() => undefined),
      ])
    }
  },
  component: Home,
})

function Home() {
  const t = useT()
  const me = useQuery(meQuery())
  const authenticated = me.data?.authenticated === true

  return authenticated ? (
    <MemberHome name={me.data?.display_name ?? ''} />
  ) : (
    <main className="page page--narrow" data-home-anonymous>
      <div className={formStyles.topLinks}>
        <span className={formStyles.brand}>{t('app.name')}</span>
        <Link to="/settings" className={styles.topLink}>
          {t('nav.settings')}
        </Link>
      </div>
      <div className={formStyles.homeHero}>
        <h1 className={formStyles.homeTitle}>{t('app.tagline')}</h1>
        <p className={formStyles.lead}>{t('app.intro')}</p>
        <p className={formStyles.lead} style={{ marginTop: 'var(--s-4)' }}>
          {t('home.signInHint')}
        </p>
        <div className={formStyles.actions}>
          <ButtonLink to="/login" search={{}}>
            {t('nav.signIn')}
          </ButtonLink>
        </div>
      </div>
    </main>
  )
}

function MemberHome({ name }: { name: string }) {
  const t = useT()
  const locale = useLocale()
  const years = useQuery(yearsQuery())
  const events = useQuery(eventsQuery())
  const latest = years.data?.[0] ?? null
  const rows = homeRows(events.data?.items, latest?.events)
  const portrait = latest?.events.flatMap((e) => e.of_you_items ?? [])[0]
  const portraitSrc = portrait?.variants?.thumb ?? portrait?.variants?.small

  return (
    <>
      <main className={`page ${styles.main} has-bar`} data-home>
        <div className={formStyles.topLinks}>
          <span className={formStyles.brand}>{t('app.name')}</span>
          <nav className={styles.topNav} aria-label={t('nav.settings')}>
            <Link to="/manage" className={styles.topLink}>
              {t('nav.manage')}
            </Link>
            <Link to="/search" search={{}} className={styles.topLink}>
              {t('nav.search')}
            </Link>
            <Link to="/settings" className={styles.topLink}>
              {t('nav.settings')}
            </Link>
          </nav>
        </div>
        <header className={styles.greeting}>
          {portraitSrc ? (
            <img className={styles.portrait} src={portraitSrc} alt="" />
          ) : (
            <span className={styles.portrait} aria-hidden="true" />
          )}
          <div>
            <h1 className={styles.hello}>{t('home.greeting', { name })}</h1>
            {latest ? (
              <Link
                to="/year/$year"
                params={{ year: String(latest.year) }}
                className={styles.moments}
                data-moments
              >
                {t('home.moments', { count: latest.moments })}
              </Link>
            ) : null}
          </div>
        </header>

        <Suggestions />

        <section className={styles.section}>
          <h2 className="eyebrow">{t('home.albumsIn')}</h2>
          {rows.length === 0 && (years.isSuccess || years.isError) && events.isFetched ? (
            <p className={formStyles.lead}>{t('home.empty')}</p>
          ) : null}
          <ul className={styles.albums}>
            {rows.map((row) => {
              const ofYou = row.summary?.of_you_items ?? []
              const cover = row.summary?.cover ?? row.event?.cover
              const analyzing = row.summary?.analyzing || (row.event?.counts.processing ?? 0) > 0
              return (
                <li key={row.slug} className={styles.album} data-home-event={row.slug}>
                  {ofYou.length > 0 ? (
                    <FanStack items={ofYou} label={row.title} />
                  ) : (
                    <Link to="/e/$slug" params={{ slug: row.slug }} className={styles.cover}>
                      {cover?.small ? (
                        <img src={cover.medium ?? cover.small} alt="" loading="lazy" />
                      ) : null}
                    </Link>
                  )}
                  <div className={styles.albumText}>
                    {row.summary?.of_you ? (
                      <span className={styles.ofYou}>
                        {t('common.ofYou', { count: row.summary.of_you })}
                      </span>
                    ) : null}
                    <Link to="/e/$slug" params={{ slug: row.slug }} className={styles.albumTitle}>
                      {row.title}
                    </Link>
                    <span className={styles.albumMeta}>
                      {formatEventDate(row.starts_at, locale, row.timezone)} ·{' '}
                      {t('common.photos', { count: row.photos })}
                      {analyzing ? ` · ${t('home.stillAnalyzing')}` : ''}
                    </span>
                  </div>
                </li>
              )
            })}
          </ul>
          {years.data && years.data.length > 1 ? (
            <ul className={styles.yearLinks}>
              {years.data.map((y) => (
                <li key={y.year}>
                  <Link to="/year/$year" params={{ year: String(y.year) }}>
                    {t('home.yourYear', { year: y.year })}
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      </main>
      <BottomBar>
        <ButtonLink to="/people" variant="secondary">
          {t('nav.people')}
        </ButtonLink>
        <ButtonLink to="/new">{t('home.newEvent')}</ButtonLink>
      </BottomBar>
    </>
  )
}
