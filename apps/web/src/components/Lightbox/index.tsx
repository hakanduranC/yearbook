import {
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import { useLocale, useT } from '~/i18n'
import type { GridItem, MediaDetail } from '~/lib/api/types'
import { formatTime } from '~/lib/format'
import { originalUrl } from '~/lib/queries/media'
import styles from './Lightbox.module.css'

interface Props {
  item: GridItem | MediaDetail
  index: number
  total: number
  previous: GridItem | null
  next: GridItem | null
  eventTitle: string
  timeZone?: string
  onClose: () => void
  onNavigate: (id: string) => void
  onToggleLike: (id: string, liked: boolean) => void
  onShared?: (how: 'native' | 'copied') => void
  /** Opens the people sheet (faces in this photo). */
  onPeople?: () => void
  /** Asks to delete; shown only when the detail says `can_delete`. */
  onDelete?: () => void
}

function Heart({ filled }: { filled: boolean }) {
  return (
    <svg viewBox="0 0 20 20" fill={filled ? 'currentColor' : 'none'} aria-hidden="true">
      <path
        d="M10 17.5 2.9 10.3a4.3 4.3 0 0 1 6.1-6.1l1 1 1-1a4.3 4.3 0 0 1 6.1 6.1L10 17.5Z"
        stroke="currentColor"
        strokeWidth="1.5"
      />
    </svg>
  )
}

export function Lightbox({
  item,
  index,
  total,
  previous,
  next,
  eventTitle,
  timeZone,
  onClose,
  onNavigate,
  onToggleLike,
  onShared,
  onPeople,
  onDelete,
}: Props) {
  const t = useT()
  const locale = useLocale()
  const ref = useRef<HTMLDialogElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const [dragX, setDragX] = useState(0)
  const pointer = useRef<{ id: number; x: number; y: number; moved: boolean } | null>(null)

  // Open once mounted. No programmatic close: React may disconnect and reconnect this effect
  // around Suspense boundaries, and a close() here would fire `close` and navigate away.
  // Removing the element on unmount drops it from the top layer without an event.
  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) dialog.showModal()
  }, [])

  // Keyboard: arrows and Esc (Esc fires cancel on the dialog).
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === 'ArrowLeft' && previous) onNavigate(previous.id)
      if (ev.key === 'ArrowRight' && next) onNavigate(next.id)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [previous, next, onNavigate])

  // Preload neighbors.
  useEffect(() => {
    for (const n of [previous, next]) {
      const src = n?.variants?.large ?? n?.variants?.medium ?? n?.poster
      if (src) {
        const img = new Image()
        img.src = src
      }
    }
  }, [previous, next])

  const onPointerDown = (ev: ReactPointerEvent) => {
    if (ev.pointerType === 'mouse' && ev.button !== 0) return
    pointer.current = { id: ev.pointerId, x: ev.clientX, y: ev.clientY, moved: false }
  }
  const onPointerMove = (ev: ReactPointerEvent) => {
    const p = pointer.current
    if (!p || p.id !== ev.pointerId) return
    const dx = ev.clientX - p.x
    const dy = ev.clientY - p.y
    if (!p.moved && Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy)) {
      p.moved = true
      stageRef.current?.setPointerCapture(ev.pointerId)
    }
    if (p.moved) setDragX(dx)
  }
  const endPointer = useCallback(
    (ev: ReactPointerEvent) => {
      const p = pointer.current
      if (!p || p.id !== ev.pointerId) return
      pointer.current = null
      const dx = ev.clientX - p.x
      setDragX(0)
      if (p.moved) {
        if (dx < -60 && next) onNavigate(next.id)
        else if (dx > 60 && previous) onNavigate(previous.id)
      }
    },
    [next, previous, onNavigate],
  )

  const detail = item as Partial<MediaDetail>
  const time = item.captured_at ? formatTime(item.captured_at, locale, timeZone) : ''
  const uploader = detail.uploader
  const meta = uploader?.is_you
    ? t('lightbox.uploadedByYou', { time })
    : uploader?.display_name
      ? t('lightbox.uploadedBy', { name: uploader.display_name, time })
      : time

  const share = async () => {
    const url = window.location.href
    const title = t('lightbox.shareTitle', { title: eventTitle })
    if (typeof navigator.share === 'function') {
      try {
        await navigator.share({ title, url })
        onShared?.('native')
        return
      } catch {
        // cancelled or unsupported, fall back to copy
      }
    }
    try {
      await navigator.clipboard.writeText(url)
      onShared?.('copied')
    } catch {
      // ignore
    }
  }

  const large = item.variants?.large ?? item.variants?.medium ?? item.variants?.small
  const ready = item.state === 'ready' && !item.processing

  return (
    <dialog
      ref={ref}
      className={styles.dialog}
      aria-label={t('lightbox.counter', { index, total })}
      onCancel={(ev) => {
        ev.preventDefault()
        onClose()
      }}
      onClose={onClose}
      data-lightbox={item.id}
    >
      <div className={styles.top}>
        <button type="button" className={styles.icon} onClick={onClose} aria-label={t('nav.close')}>
          <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path d="m5 5 10 10M15 5 5 15" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </button>
        <span>{total > 0 ? t('lightbox.counter', { index, total }) : ''}</span>
        <span />
      </div>
      <div
        ref={stageRef}
        className={styles.stage}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endPointer}
        onPointerCancel={endPointer}
      >
        {item.kind === 'video' && item.video_url ? (
          <video
            className={styles.media}
            controls
            poster={item.poster}
            src={item.video_url}
            playsInline
            preload="metadata"
          />
        ) : ready && large ? (
          <img
            className={styles.media}
            src={large}
            srcSet={[
              item.variants?.small ? `${item.variants.small} 640w` : null,
              item.variants?.medium ? `${item.variants.medium} 1280w` : null,
              item.variants?.large ? `${item.variants.large} 2048w` : null,
            ]
              .filter(Boolean)
              .join(', ')}
            sizes="100vw"
            alt=""
            draggable={false}
            style={{ transform: dragX ? `translateX(${dragX}px)` : undefined }}
          />
        ) : (
          <span className={styles.meta}>{t('photos.processing')}</span>
        )}
        {previous ? (
          <button
            type="button"
            className={`${styles.nav} ${styles.prev}`}
            onClick={() => onNavigate(previous.id)}
            aria-label={t('lightbox.previous')}
          >
            <svg width="22" height="22" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="M12.5 4 6.5 10l6 6" stroke="currentColor" strokeWidth="1.5" />
            </svg>
          </button>
        ) : null}
        {next ? (
          <button
            type="button"
            className={`${styles.nav} ${styles.next}`}
            onClick={() => onNavigate(next.id)}
            aria-label={t('lightbox.next')}
          >
            <svg width="22" height="22" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="m7.5 4 6 6-6 6" stroke="currentColor" strokeWidth="1.5" />
            </svg>
          </button>
        ) : null}
      </div>
      <div className={styles.footer}>
        <div
          className={[styles.meta, uploader?.is_you ? styles.metaYou : null]
            .filter(Boolean)
            .join(' ')}
        >
          {meta}
        </div>
        <div className={styles.actions}>
          <button
            type="button"
            className={[styles.action, item.liked ? styles.liked : null].filter(Boolean).join(' ')}
            aria-pressed={item.liked}
            aria-label={item.liked ? t('lightbox.unlike') : t('lightbox.like')}
            onClick={() => onToggleLike(item.id, !item.liked)}
            data-like
          >
            <Heart filled={item.liked} />
            {item.like_count > 0 ? item.like_count : null}
          </button>
          <a className={styles.action} href={originalUrl(item.id)} download>
            {t('common.download')}
          </a>
          <button type="button" className={styles.action} onClick={share}>
            {t('common.share')}
          </button>
        </div>
        {onPeople || (onDelete && detail.can_delete) ? (
          <div className={styles.actions}>
            {onPeople ? (
              <button type="button" className={styles.action} onClick={onPeople} data-people>
                {t('lightbox.people')}
              </button>
            ) : null}
            {onDelete && detail.can_delete ? (
              <button
                type="button"
                className={`${styles.action} ${styles.danger}`}
                onClick={onDelete}
                data-delete
              >
                {t('common.delete')}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </dialog>
  )
}
