import { describe, expect, it } from 'vitest'
import {
  clampIndex,
  FAN_MAX_VISIBLE,
  FAN_OFFSET_PX,
  FAN_SPREAD_DEG,
  fanLayout,
  settle,
  transformOf,
} from '~/lib/fan'

describe('clampIndex', () => {
  it('keeps the index inside the stack', () => {
    expect(clampIndex(-1, 4)).toBe(0)
    expect(clampIndex(9, 4)).toBe(3)
    expect(clampIndex(2, 4)).toBe(2)
    expect(clampIndex(3, 0)).toBe(0)
  })
})

describe('fanLayout at rest', () => {
  it('puts the active card flat on top and fans the rest to the right', () => {
    const top = fanLayout(1, 1, 4, 0, 300)
    expect(top).toMatchObject({ x: 0, rotate: 0, scale: 1, opacity: 1 })
    const behind = fanLayout(2, 1, 4, 0, 300)
    expect(behind.x).toBe(FAN_OFFSET_PX)
    expect(behind.rotate).toBe(FAN_SPREAD_DEG)
    expect(behind.scale).toBeLessThan(1)
    expect(behind.z).toBeLessThan(top.z)
  })

  it('hides cards deeper than the visible count', () => {
    expect(fanLayout(FAN_MAX_VISIBLE, 0, 6, 0, 300).opacity).toBe(0)
    expect(fanLayout(FAN_MAX_VISIBLE - 1, 0, 6, 0, 300).opacity).toBe(1)
  })

  it('parks swiped cards off-screen to the left', () => {
    const gone = fanLayout(0, 2, 4, 0, 300)
    expect(gone.x).toBeLessThan(-300)
    expect(gone.opacity).toBe(0)
    const previous = fanLayout(1, 2, 4, 0, 300)
    expect(previous.opacity).toBe(1)
  })
})

describe('fanLayout while dragging', () => {
  it('follows the pointer with the active card and rotates with the drag', () => {
    const l = fanLayout(0, 0, 3, -150, 300)
    expect(l.x).toBe(-150)
    expect(l.rotate).toBe(-6)
  })

  it('pulls the next card forward during a leftward drag', () => {
    const rest = fanLayout(1, 0, 3, 0, 300)
    const pulled = fanLayout(1, 0, 3, -150, 300)
    expect(pulled.x).toBeLessThan(rest.x)
    expect(pulled.scale).toBeGreaterThan(rest.scale)
  })

  it('brings the previous card back during a rightward drag', () => {
    const half = fanLayout(0, 1, 3, 150, 300)
    expect(half.x).toBeCloseTo(-300 * 1.2 * 0.5, 5)
    const full = fanLayout(0, 1, 3, 300, 300)
    expect(full.x).toBeCloseTo(0, 5)
    expect(full.rotate).toBeCloseTo(0, 5)
  })
})

describe('settle', () => {
  it('snaps back below the threshold', () => {
    expect(settle(1, 4, -40, 300)).toBe(1)
    expect(settle(1, 4, 40, 300)).toBe(1)
  })

  it('advances or retreats past a quarter of the width', () => {
    expect(settle(1, 4, -100, 300)).toBe(2)
    expect(settle(1, 4, 100, 300)).toBe(0)
  })

  it('accepts a quick flick even when short', () => {
    expect(settle(1, 4, -30, 300, 0.8)).toBe(2)
    expect(settle(1, 4, 30, 300, -0.8)).toBe(0)
  })

  it('never leaves the stack', () => {
    expect(settle(3, 4, -200, 300)).toBe(3)
    expect(settle(0, 4, 200, 300)).toBe(0)
  })
})

describe('transformOf', () => {
  it('renders a stable transform string', () => {
    expect(transformOf({ x: 10, rotate: 5, scale: 0.96, z: 1, opacity: 1 })).toBe(
      'translateX(10.0px) rotate(5.00deg) scale(0.960)',
    )
  })
})
