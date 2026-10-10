import { Link } from '@tanstack/react-router'
import { useLocale, useT } from '~/i18n'
import type { Event } from '~/lib/api/types'
import { formatEventDate } from '~/lib/format'
import styles from './EventCard.module.css'

interface Props {
  event: Event
  variant?: 'hero' | 'list'
}

export function EventCard({ event, variant = 'list' }: Props) {
  const t = useT()
  const locale = useLocale()
  const date = formatEventDate(event.starts_at, locale, event.timezone)
  const photos = t('common.photos', { count: event.counts.photos })
  const processing = event.counts.processing > 0 ? ` · ${t('home.analyzing')}` : ''
  const ofYou = event.counts.of_you ? t('common.ofYou', { count: event.counts.of_you }) : null

  if (variant === 'hero') {
    return (
      <Link to="/e/$slug" params={{ slug: event.slug }} className={styles.hero}>
        {event.cover?.medium ? (
          <img
            className={styles.heroImage}
            src={event.cover.medium}
            srcSet={heroSrcSet(event)}
            alt=""
          />
        ) : null}
        <div className={styles.heroText}>
          {ofYou ? <div className={styles.ofYou}>{ofYou}</div> : null}
          <div className={styles.title}>{event.title}</div>
          <div className={styles.meta}>
            {date} · {photos}
            {processing}
          </div>
        </div>
      </Link>
    )
  }

  return (
    <Link to="/e/$slug" params={{ slug: event.slug }} className={styles.list}>
      {event.cover?.thumb ? (
        <img
          className={styles.thumb}
          src={event.cover.small ?? event.cover.thumb}
          alt=""
          loading="lazy"
        />
      ) : (
        <div className={styles.thumb} />
      )}
      <div>
        {ofYou ? <div className={styles.ofYou}>{ofYou}</div> : null}
        <div className={styles.title}>{event.title}</div>
        <div className={styles.meta}>
          {date} · {photos}
          {processing}
        </div>
      </div>
    </Link>
  )
}

function heroSrcSet(event: Event): string | undefined {
  const c = event.cover
  if (!c) return undefined
  const parts = [
    c.small ? `${c.small} 640w` : null,
    c.medium ? `${c.medium} 1280w` : null,
    c.large ? `${c.large} 2048w` : null,
  ]
  return parts.filter(Boolean).join(', ') || undefined
}
