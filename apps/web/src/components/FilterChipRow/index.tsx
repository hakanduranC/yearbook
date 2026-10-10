import { Link } from '@tanstack/react-router'
import { useT } from '~/i18n'
import { type MediaFilter, mediaFilters } from '~/lib/api/types'
import styles from './FilterChipRow.module.css'

interface Props {
  slug: string
  current: MediaFilter
}

export function FilterChipRow({ slug, current }: Props) {
  const t = useT()
  return (
    <nav className={styles.row} aria-label={t('photos.title')}>
      {mediaFilters.map((filter) => (
        <Link
          key={filter}
          to="/e/$slug/photos"
          params={{ slug }}
          search={filter === 'all' ? {} : { filter }}
          replace
          resetScroll={false}
          className={[styles.chip, filter === 'mine' ? styles.chipYou : null]
            .filter(Boolean)
            .join(' ')}
          aria-current={filter === current ? 'true' : undefined}
          data-filter={filter}
        >
          {t(`photos.filter.${filter}`)}
        </Link>
      ))}
    </nav>
  )
}
