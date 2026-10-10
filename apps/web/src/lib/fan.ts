/** Geometry for the fanned, swipeable photo stack on Home. Pure functions, tested in isolation. */

export interface FanLayout {
  x: number
  rotate: number
  scale: number
  z: number
  /** 0 hides a card that was swiped away. */
  opacity: number
}

export const FAN_OFFSET_PX = 10
export const FAN_SPREAD_DEG = 5
export const FAN_SCALE_STEP = 0.04
export const FAN_MAX_VISIBLE = 4
export const SWIPE_FRACTION = 0.25
export const FLICK_PX_PER_MS = 0.5

export function clampIndex(index: number, count: number): number {
  if (count <= 0) return 0
  return Math.min(count - 1, Math.max(0, index))
}

/**
 * Layout of card `index` while `active` is on top and the pointer has moved `dragX` px.
 * Cards behind the active one fan to the right; swiped cards wait off-screen to the left
 * and slide back in during a rightward drag.
 */
export function fanLayout(
  index: number,
  active: number,
  count: number,
  dragX: number,
  width: number,
): FanLayout {
  const offset = index - active
  const w = Math.max(1, width)
  if (offset === 0) {
    return {
      x: dragX,
      rotate: (dragX / w) * 12,
      scale: 1,
      z: count + 1,
      opacity: 1,
    }
  }
  if (offset > 0) {
    const pull = dragX < 0 ? Math.min(1, -dragX / w) : 0
    const o = offset - pull
    return {
      x: o * FAN_OFFSET_PX,
      rotate: o * FAN_SPREAD_DEG,
      scale: 1 - FAN_SCALE_STEP * o,
      z: count - offset,
      opacity: offset >= FAN_MAX_VISIBLE ? 0 : 1,
    }
  }
  // Already swiped away. Only the immediate predecessor returns while dragging right.
  const comeback = offset === -1 && dragX > 0 ? Math.min(1, dragX / w) : 0
  return {
    x: -w * 1.2 * (1 - comeback),
    rotate: -12 * (1 - comeback),
    scale: 1,
    z: count + 2,
    opacity: offset === -1 ? 1 : 0,
  }
}

/** Where the stack settles after the pointer lifts. */
export function settle(
  active: number,
  count: number,
  dragX: number,
  width: number,
  velocityPxPerMs = 0,
): number {
  const w = Math.max(1, width)
  const far = Math.abs(dragX) >= w * SWIPE_FRACTION
  const flick = Math.abs(velocityPxPerMs) >= FLICK_PX_PER_MS
  const direction = dragX < 0 ? 1 : dragX > 0 ? -1 : 0
  if (direction === 0 || !(far || flick)) return active
  return clampIndex(active + direction, count)
}

export function transformOf(layout: FanLayout): string {
  return `translateX(${layout.x.toFixed(1)}px) rotate(${layout.rotate.toFixed(2)}deg) scale(${layout.scale.toFixed(3)})`
}
