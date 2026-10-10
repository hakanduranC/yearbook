import { describe, expect, it } from 'vitest'
import { buildRows, columnsFor, flattenPages, groupItems, rowModel } from '~/lib/grouping'
import { group, item, page } from './helpers'

const evening = group('evening', '2026-06-14T15:00:00Z', '2026-06-14T20:00:00Z', 2)
const night = group('night', '2026-06-14T20:00:00Z', '2026-06-15T03:00:00Z', 3)

describe('flattenPages', () => {
  it('dedupes items across pages and merges groups newest first', () => {
    const a = item({ id: 'a' })
    const b = item({ id: 'b' })
    const { items, groups } = flattenPages([
      page([a, b], [night]),
      page([b, item({ id: 'c' })], [evening]),
    ])
    expect(items.map((i) => i.id)).toEqual(['a', 'b', 'c'])
    expect(groups.map((g) => g.label)).toEqual(['night', 'evening'])
  })

  it('drops removed tombstones', () => {
    const { items } = flattenPages([page([item({ id: 'a', state: 'removed' }), item({ id: 'b' })])])
    expect(items.map((i) => i.id)).toEqual(['b'])
  })
})

describe('groupItems', () => {
  it('assigns by captured_at within [start, end)', () => {
    const items = [
      item({ id: 'n1', captured_at: '2026-06-14T22:00:00Z' }),
      item({ id: 'e1', captured_at: '2026-06-14T16:00:00Z' }),
      item({ id: 'edge', captured_at: '2026-06-14T20:00:00Z' }),
    ]
    const groups = groupItems(items, [evening, night])
    expect(groups.map((g) => [g.label, g.items.map((i) => i.id)])).toEqual([
      ['night', ['n1', 'edge']],
      ['evening', ['e1']],
    ])
  })

  it('puts fresh items without a matching group into a leading "new" group and undated ready items last', () => {
    const items = [
      item({ id: 'q', state: 'queued', processing: true, captured_at: null }),
      item({ id: 'e1', captured_at: '2026-06-14T16:00:00Z' }),
      item({ id: 'u', captured_at: null }),
      item({ id: 'future', captured_at: '2027-01-01T00:00:00Z' }),
    ]
    const groups = groupItems(items, [evening])
    expect(groups.map((g) => g.label)).toEqual(['new', 'evening', 'other'])
    expect(groups[0]?.items.map((i) => i.id)).toEqual(['q', 'future'])
    expect(groups[2]?.items.map((i) => i.id)).toEqual(['u'])
  })

  it('maps unknown server labels to other', () => {
    const groups = groupItems(
      [item({ id: 'x', captured_at: '2026-06-14T16:00:00Z' })],
      [group('brunch', evening.start, evening.end)],
    )
    expect(groups[0]?.label).toBe('other')
  })
})

describe('buildRows', () => {
  it('emits one header per group and rows of `columns` items', () => {
    const items = Array.from({ length: 7 }, (_, i) =>
      item({ id: `i${i}`, captured_at: '2026-06-14T22:00:00Z' }),
    )
    const model = buildRows(groupItems(items, [night]), 3)
    expect(model.rows.map((r) => r.type)).toEqual(['header', 'row', 'row', 'row'])
    const rows = model.rows.filter((r) => r.type === 'row')
    expect(rows.map((r) => (r.type === 'row' ? r.items.length : 0))).toEqual([3, 3, 1])
    expect(model.items.map((i) => i.id)).toEqual(items.map((i) => i.id))
    expect(model.indexById.get('i4')).toBe(4)
  })

  it('never produces zero columns', () => {
    const model = buildRows(groupItems([item({ id: 'a' })], [night]), 0)
    expect(model.rows.filter((r) => r.type === 'row')).toHaveLength(1)
  })

  it('rowModel composes the pipeline', () => {
    const model = rowModel(
      [page([item({ id: 'a', captured_at: '2026-06-14T22:00:00Z' })], [night])],
      3,
    )
    expect(model.rows).toHaveLength(2)
  })
})

describe('columnsFor', () => {
  it('matches the breakpoints', () => {
    expect(columnsFor(390)).toBe(3)
    expect(columnsFor(599)).toBe(3)
    expect(columnsFor(600)).toBe(5)
    expect(columnsFor(1023)).toBe(5)
    expect(columnsFor(1024)).toBe(6)
    expect(columnsFor(1439)).toBe(6)
    expect(columnsFor(1440)).toBe(8)
  })
})
