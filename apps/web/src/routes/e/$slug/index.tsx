import { useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ButtonLink } from '~/components/Button'
import { type Locale, t as translate, useLocale, useT } from '~/i18n'
import { publicOrigin } from '~/lib/env'
import { formatEventDate } from '~/lib/format'
import { eventQuery, isHost } from '~/lib/queries/event'
import styles from '~/styles/pages/landing.module.css'

export const Route = createFileRoute('/e/$slug/')({
  loader: async ({ context: { queryClient }, params }) => {
    const event = await queryClient.ensureQueryData(eventQuery(params.slug))
    return {
      origin: publicOrigin(),
      title: event.title,
      hostName: event.host.display_name,
      image: event.cover?.large ?? event.cover?.medium ?? null,
    }
  },
  head: ({ loaderData, params, matches }) => {
    if (!loaderData) return {}
    const locale = ((matches[0]?.loaderData as { locale?: Locale } | undefined)?.locale ??
      'de') as Locale
    const url = `${loaderData.origin}/e/${encodeURIComponent(params.slug)}`
    const description = translate(locale, 'landing.ogDescription', { title: loaderData.title })
    return {
      meta: [
        { title: `${loaderData.title} · Yearbook` },
        { name: 'description', content: description },
        { property: 'og:type', content: 'website' },
        { property: 'og:title', content: loaderData.title },
        { property: 'og:description', content: description },
        { property: 'og:url', content: url },
        { property: 'og:site_name', content: 'Yearbook' },
        ...(loaderData.image
          ? [
              { property: 'og:image', content: loaderData.image },
              { name: 'twitter:card', content: 'summary_large_image' },
              { name: 'twitter:image', content: loaderData.image },
            ]
          : [{ name: 'twitter:card', content: 'summary' }]),
      ],
      links: [{ rel: 'canonical', href: url }],
    }
  },
  component: Landing,
})

function Landing() {
  const t = useT()
  const locale = useLocale()
  const { slug } = Route.useParams()
  const { data: event } = useSuspenseQuery(eventQuery(slug))
  const host = isHost(event)
  const when = [formatEventDate(event.starts_at, locale, event.timezone), event.location]
    .filter(Boolean)
    .join(' · ')
  const canUpload = event.guest_upload || host
  const canView = event.guest_view || host

  return (
    <main data-landing>
      <section className={styles.hero}>
        {event.cover?.large ? (
          <img
            className={styles.cover}
            src={event.cover.medium ?? event.cover.large}
            srcSet={[
              event.cover.small ? `${event.cover.small} 640w` : null,
              event.cover.medium ? `${event.cover.medium} 1280w` : null,
              event.cover.large ? `${event.cover.large} 2048w` : null,
            ]
              .filter(Boolean)
              .join(', ')}
            sizes="100vw"
            alt=""
            fetchPriority="high"
          />
        ) : null}
        <div className={styles.heroText}>
          <span className="eyebrow">{t('landing.invites', { name: event.host.display_name })}</span>
          <h1 className={styles.title}>{event.title}</h1>
          <span className={styles.when}>{when}</span>
        </div>
      </section>
      <section className={styles.body}>
        <p className={styles.lead}>{t('landing.lead')}</p>
        <p className={styles.sub}>{t('landing.sub')}</p>
        <div className={styles.actions}>
          {canUpload ? (
            <ButtonLink to="/e/$slug/upload" params={{ slug }}>
              {t('landing.add')}
            </ButtonLink>
          ) : (
            <p className={styles.sub}>{t('landing.uploadOff')}</p>
          )}
          {canView ? (
            <ButtonLink to="/e/$slug/photos" params={{ slug }} search={{}} variant="secondary">
              {t('landing.see')}
            </ButtonLink>
          ) : (
            <p className={styles.sub}>{t('landing.viewOff')}</p>
          )}
        </div>
      </section>
      {host ? (
        <nav className={styles.hostLinks} aria-label="Host">
          <Link to="/e/$slug/share" params={{ slug }}>
            {t('event.share')}
          </Link>
          <Link to="/e/$slug/uploads" params={{ slug }}>
            {t('event.uploads')}
          </Link>
          <Link to="/e/$slug/settings" params={{ slug }}>
            {t('event.settings')}
          </Link>
        </nav>
      ) : null}
    </main>
  )
}
