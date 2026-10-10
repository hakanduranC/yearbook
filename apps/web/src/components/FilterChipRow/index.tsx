import { Link } from '@tanstack/react-router'
import { useT } from '~/i18n'
import type { SavedCommand } from '~/lib/api/types'
import { type MediaFilter, mediaFilters, personIdOf } from '~/lib/api/types'
import styles from './FilterChipRow.module.css'

interface Props {
  slug: string
  current: MediaFilter
  /** The `me` chip appears once the viewer has a claimed person. */
  hasMe?: boolean
  /** Name of the person when `current` is a person filter. */
  personName?: string | null
  commands?: SavedCommand[]
}

export function FilterChipRow({ slug, current, hasMe, personName, commands = [] }: Props) {
  const t = useT()
  const personId = personIdOf(current)
  const filters = mediaFilters.filter((f) => f !== 'me' || hasMe)
  return (
    <nav className={styles.row} aria-label={t('photos.title')}>
      {filters.map((filter) => (
        <Link
          key={filter}
          to="/e/$slug/photos"
          params={{ slug }}
          search={filter === 'all' ? {} : { filter }}
          replace
          resetScroll={false}
          className={[styles.chip, filter === 'mine' || filter === 'me' ? styles.chipYou : null]
            .filter(Boolean)
            .join(' ')}
          aria-current={filter === current ? 'true' : undefined}
          data-filter={filter}
        >
          {t(`photos.filter.${filter}`)}
        </Link>
      ))}
      {personId ? (
        <Link
          to="/e/$slug/photos"
          params={{ slug }}
          search={{ filter: current }}
          replace
          resetScroll={false}
          className={styles.chip}
          aria-current="true"
          data-filter="person"
        >
          {personName ?? t('people.unknown')}
        </Link>
      ) : null}
      {commands.map((c) => (
        <Link
          key={c.id}
          to="/e/$slug/search"
          params={{ slug }}
          search={{ command: c.id }}
          className={`${styles.chip} ${styles.chipSaved}`}
          data-command={c.id}
          title={c.description}
        >
          {c.label}
        </Link>
      ))}
    </nav>
  )
}
