import { Link, type LinkProps } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { useT } from '~/i18n'
import type { GridItem } from '~/lib/api/types'
import { formatDuration } from '~/lib/format'
import styles from './MediaTile.module.css'

interface Props {
  item: GridItem
  aspect?: 'square' | '4:3' | '3:4'
  link?: Pick<LinkProps, 'to' | 'params' | 'search'>
  onOpen?: () => void
  selectMode?: boolean
  selected?: boolean
  onToggle?: (id: string) => void
  /** Overlay control in the top right, e.g. a pin button. Rendered outside the link. */
  action?: ReactNode
  priority?: boolean
}

/** A non-virtualized grid cell for curated lists: highlights, albums, agent results, the library. */
export function MediaTile({
  item,
  aspect = 'square',
  link,
  onOpen,
  selectMode,
  selected,
  onToggle,
  action,
  priority,
}: Props) {
  const t = useT()
  const ready = item.state === 'ready' && !item.processing
  const thumb =
    aspect === 'square'
      ? (item.variants?.thumb ?? item.poster)
      : (item.variants?.small ?? item.poster)
  const label =
    item.kind === 'video' ? t('common.videos', { count: 1 }) : t('common.photos', { count: 1 })
  const cls = [
    styles.cell,
    aspect === '4:3' ? styles.wide : aspect === '3:4' ? styles.tall : null,
    selectMode ? styles.selectable : null,
    selected ? styles.selected : null,
  ]
    .filter(Boolean)
    .join(' ')

  const content = (
    <>
      {ready && thumb ? (
        <img
          className={styles.img}
          src={thumb}
          srcSet={
            item.variants?.small && item.variants?.thumb
              ? `${item.variants.thumb} 256w, ${item.variants.small} 640w`
              : undefined
          }
          sizes="(max-width: 600px) 50vw, 25vw"
          alt=""
          loading={priority ? 'eager' : 'lazy'}
          decoding="async"
          draggable={false}
        />
      ) : (
        <span className={styles.processing} role="img" aria-label={t('photos.processing')} />
      )}
      <span className={styles.badges}>
        <span>{item.me ? <span className={styles.you}>{t('common.you')}</span> : null}</span>
        {item.kind === 'video' && item.duration_ms ? (
          <span className={styles.duration}>{formatDuration(item.duration_ms)}</span>
        ) : null}
      </span>
      {selectMode ? (
        <span className={styles.check} aria-hidden="true">
          {selected ? <Check /> : null}
        </span>
      ) : null}
    </>
  )

  let inner: ReactNode
  if (selectMode) {
    inner = (
      <button
        type="button"
        className={cls}
        aria-pressed={selected}
        aria-label={label}
        onClick={() => onToggle?.(item.id)}
        data-tile={item.id}
      >
        {content}
      </button>
    )
  } else if (link) {
    inner = (
      <Link {...link} resetScroll={false} className={cls} aria-label={label} data-tile={item.id}>
        {content}
      </Link>
    )
  } else if (onOpen) {
    inner = (
      <button type="button" className={cls} aria-label={label} onClick={onOpen} data-tile={item.id}>
        {content}
      </button>
    )
  } else {
    inner = (
      <div className={cls} data-tile={item.id}>
        {content}
      </div>
    )
  }
  if (!action) return inner
  return (
    <div className={styles.withAction}>
      {inner}
      <span className={styles.action}>{action}</span>
    </div>
  )
}

function Check() {
  return (
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="m4 10.5 4 4 8-9" stroke="#fff" strokeWidth="2.2" strokeLinecap="square" />
    </svg>
  )
}
