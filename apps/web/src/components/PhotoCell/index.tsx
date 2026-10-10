import { Link } from '@tanstack/react-router'
import { memo } from 'react'
import { useT } from '~/i18n'
import type { GridItem, MediaFilter } from '~/lib/api/types'
import { formatDuration } from '~/lib/format'
import styles from './PhotoCell.module.css'

interface Props {
  item: GridItem
  slug: string
  filter: MediaFilter
  selectMode: boolean
  selected: boolean
  onToggle: (id: string) => void
  priority?: boolean
}

function Heart() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path d="M10 17.5 2.9 10.3a4.3 4.3 0 0 1 6.1-6.1l1 1 1-1a4.3 4.3 0 0 1 6.1 6.1L10 17.5Z" />
    </svg>
  )
}

export const PhotoCell = memo(function PhotoCell({
  item,
  slug,
  filter,
  selectMode,
  selected,
  onToggle,
  priority,
}: Props) {
  const t = useT()
  const ready = item.state === 'ready' && !item.processing
  const thumb = item.variants?.thumb ?? item.poster
  const small = item.variants?.small
  const label =
    item.kind === 'video' ? t('common.videos', { count: 1 }) : t('common.photos', { count: 1 })

  const content = (
    <>
      {ready && thumb ? (
        <img
          className={styles.img}
          src={thumb}
          srcSet={small ? `${thumb} 256w, ${small} 640w` : undefined}
          sizes="(max-width: 600px) 33vw, (max-width: 1024px) 20vw, 16vw"
          alt=""
          loading={priority ? 'eager' : 'lazy'}
          decoding="async"
          draggable={false}
        />
      ) : (
        <span
          className={styles.processing}
          style={{ position: 'absolute', inset: 0 }}
          role="img"
          aria-label={t('photos.processing')}
        />
      )}
      <span className={styles.badges}>
        <span>{item.me ? <span className={styles.you}>{t('common.you')}</span> : null}</span>
        <span style={{ display: 'inline-flex', gap: 2 }}>
          {item.like_count > 0 ? (
            <span className={styles.likes}>
              <Heart />
              {item.like_count}
            </span>
          ) : null}
          {item.kind === 'video' && item.duration_ms ? (
            <span className={styles.duration}>{formatDuration(item.duration_ms)}</span>
          ) : null}
        </span>
      </span>
      {selectMode ? (
        <span className={styles.check} aria-hidden="true">
          {selected ? <Check /> : null}
        </span>
      ) : null}
    </>
  )

  const cls = [
    styles.cell,
    selectMode ? styles.selectable : null,
    selected ? styles.selected : null,
  ]
    .filter(Boolean)
    .join(' ')

  if (selectMode) {
    return (
      <button
        type="button"
        className={cls}
        aria-pressed={selected}
        aria-label={label}
        onClick={() => onToggle(item.id)}
        data-cell={item.id}
      >
        {content}
      </button>
    )
  }

  return (
    <Link
      to="/e/$slug/photos/$photoId"
      params={{ slug, photoId: item.id }}
      search={filter === 'all' ? {} : { filter }}
      resetScroll={false}
      className={cls}
      aria-label={label}
      data-cell={item.id}
      data-state={item.state}
    >
      {content}
    </Link>
  )
})

function Check() {
  return (
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="m4 10.5 4 4 8-9" stroke="#fff" strokeWidth="2.2" strokeLinecap="square" />
    </svg>
  )
}
