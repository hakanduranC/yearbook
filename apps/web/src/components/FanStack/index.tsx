import {
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  useEffect,
  useRef,
  useState,
} from 'react'
import { useT } from '~/i18n'
import type { GridItem } from '~/lib/api/types'
import { clampIndex, FAN_MAX_VISIBLE, fanLayout, settle, transformOf } from '~/lib/fan'
import styles from './FanStack.module.css'

interface Props {
  items: GridItem[]
  label: string
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    const mq = matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReduced(mq.matches)
    update()
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [])
  return reduced
}

/** Up to four photos fanned into a stack; drag or arrow keys move through them. */
export function FanStack({ items, label }: Props) {
  const t = useT()
  const cards = items.slice(0, FAN_MAX_VISIBLE)
  const count = cards.length
  const [active, setActive] = useState(0)
  const [dragX, setDragX] = useState(0)
  const [dragging, setDragging] = useState(false)
  const ref = useRef<HTMLButtonElement>(null)
  const swiped = useRef(false)
  const pointer = useRef<{ id: number; x: number; y: number; t: number; moved: boolean } | null>(
    null,
  )
  const reduced = usePrefersReducedMotion()

  const width = () => ref.current?.offsetWidth ?? 300

  const onPointerDown = (ev: ReactPointerEvent) => {
    if (count < 2) return
    if (ev.pointerType === 'mouse' && ev.button !== 0) return
    pointer.current = {
      id: ev.pointerId,
      x: ev.clientX,
      y: ev.clientY,
      t: ev.timeStamp,
      moved: false,
    }
  }
  const onPointerMove = (ev: ReactPointerEvent) => {
    const p = pointer.current
    if (!p || p.id !== ev.pointerId) return
    const dx = ev.clientX - p.x
    const dy = ev.clientY - p.y
    if (!p.moved && Math.abs(dx) > 6 && Math.abs(dx) > Math.abs(dy)) {
      p.moved = true
      setDragging(true)
      ref.current?.setPointerCapture(ev.pointerId)
    }
    if (p.moved) setDragX(dx)
  }
  const endPointer = (ev: ReactPointerEvent) => {
    const p = pointer.current
    if (!p || p.id !== ev.pointerId) return
    pointer.current = null
    const dx = ev.clientX - p.x
    const dt = Math.max(1, ev.timeStamp - p.t)
    if (p.moved) {
      swiped.current = true
      setActive(settle(active, count, dx, width(), dx / dt))
    }
    setDragX(0)
    setDragging(false)
  }
  // A tap (no drag) advances; a tap after a swipe is swallowed.
  const onTap = () => {
    if (swiped.current) {
      swiped.current = false
      return
    }
    if (count > 1) setActive((a) => (a + 1) % count)
  }
  const onKeyDown = (ev: KeyboardEvent) => {
    if (ev.key === 'ArrowRight') {
      ev.preventDefault()
      setActive((a) => clampIndex(a + 1, count))
    } else if (ev.key === 'ArrowLeft') {
      ev.preventDefault()
      setActive((a) => clampIndex(a - 1, count))
    }
  }

  if (count === 0) return null
  const current = cards[clampIndex(active, count)]

  return (
    <div className={styles.wrap}>
      <button
        ref={ref}
        type="button"
        className={[styles.stack, dragging ? styles.dragging : null, reduced ? styles.still : null]
          .filter(Boolean)
          .join(' ')}
        aria-roledescription="carousel"
        aria-label={label}
        onKeyDown={onKeyDown}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endPointer}
        onPointerCancel={endPointer}
        onClick={onTap}
        data-fan
        data-active={active}
      >
        {cards.map((item, index) => {
          const layout = fanLayout(index, active, count, dragX, width())
          const src = item.variants?.small ?? item.variants?.medium ?? item.poster
          return (
            <span
              key={item.id}
              className={styles.card}
              style={{
                transform: transformOf(layout),
                zIndex: layout.z,
                opacity: layout.opacity,
              }}
              aria-hidden={index !== active}
              data-fan-card={index}
            >
              {src ? <img src={src} alt="" draggable={false} loading="lazy" /> : null}
            </span>
          )
        })}
      </button>
      {count > 1 ? (
        <div className={styles.dots} role="tablist" aria-label={label}>
          {cards.map((item, index) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={index === active}
              aria-label={t('home.photoOf', { index: index + 1, total: count })}
              className={styles.dot}
              onClick={() => setActive(index)}
            />
          ))}
        </div>
      ) : null}
      <span className="visually-hidden" aria-live="polite">
        {current ? t('home.photoOf', { index: active + 1, total: count }) : ''}
      </span>
    </div>
  )
}
