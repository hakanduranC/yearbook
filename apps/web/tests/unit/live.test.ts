import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import type { MediaPage } from '~/lib/api/types'
import {
  applyLiveEvent,
  filterAdmits,
  insertGridItem,
  parseLiveEvent,
} from '~/lib/live/applyLiveEvent'
import { keys } from '~/lib/queries/keys'
import { item, page } from './helpers'

type Data = { pages: MediaPage[]; pageParams: Array<string | null> }

function seed() {
  const qc = new QueryClient()
  const a = item({ id: 'a', like_count: 1 })
  const b = item({ id: 'b', kind: 'video', duration_ms: 5000 })
  const c = item({ id: 'c', mine: true })
  qc.setQueryData<Data>(keys.media('ev', 'all'), {
    pages: [page([a, b]), page([c], [], null)],
    pageParams: [null, 'x'],
  })
  qc.setQueryData<Data>(keys.media('ev', 'videos'), { pages: [page([b])], pageParams: [null] })
  qc.setQueryData<Data>(keys.media('ev', 'mine'), { pages: [page([c])], pageParams: [null] })
  qc.setQueryData<Data>(keys.media('other', 'all'), {
    pages: [page([item({ id: 'z' })])],
    pageParams: [null],
  })
  qc.setQueryData(keys.mediaDetail('a'), { ...a, uploader: {}, can_delete: false })
  return qc
}

const ids = (qc: QueryClient, filter: 'all' | 'videos' | 'mine' | 'best', slug = 'ev') =>
  qc.getQueryData<Data>(keys.media(slug, filter))?.pages.flatMap((p) => p.items.map((i) => i.id))

describe('filterAdmits', () => {
  it('matches the server filters', () => {
    expect(filterAdmits('all', item({ id: 'x' }))).toBe(true)
    expect(filterAdmits('videos', item({ id: 'x' }))).toBe(false)
    expect(filterAdmits('videos', item({ id: 'x', kind: 'video' }))).toBe(true)
    expect(filterAdmits('mine', item({ id: 'x', mine: true }))).toBe(true)
    expect(filterAdmits('mine', item({ id: 'x' }))).toBe(false)
    expect(filterAdmits('best', item({ id: 'x', score: 0.9 }))).toBe(true)
    expect(filterAdmits('best', item({ id: 'x' }))).toBe(false)
  })
})

describe('applyLiveEvent media.ready', () => {
  it('prepends a new item to page 0 of every list whose filter admits it', () => {
    const qc = seed()
    applyLiveEvent(qc, 'ev', { type: 'media.ready', data: item({ id: 'new', kind: 'video' }) })
    expect(ids(qc, 'all')).toEqual(['new', 'a', 'b', 'c'])
    expect(ids(qc, 'videos')).toEqual(['new', 'b'])
    expect(ids(qc, 'mine')).toEqual(['c'])
    expect(ids(qc, 'all', 'other')).toEqual(['z'])
  })

  it('replaces an existing item in place on any page', () => {
    const qc = seed()
    const ready = item({ id: 'c', mine: true, like_count: 7 })
    applyLiveEvent(qc, 'ev', { type: 'media.ready', data: ready })
    expect(ids(qc, 'all')).toEqual(['a', 'b', 'c'])
    const data = qc.getQueryData<Data>(keys.media('ev', 'all'))
    expect(data?.pages[1]?.items[0]?.like_count).toBe(7)
    expect(ids(qc, 'mine')).toEqual(['c'])
  })

  it('creates page 0 when the list is empty', () => {
    const qc = new QueryClient()
    qc.setQueryData<Data>(keys.media('ev', 'all'), { pages: [], pageParams: [] })
    insertGridItem(qc, 'ev', item({ id: 'first' }))
    expect(ids(qc, 'all')).toEqual(['first'])
  })

  it('leaves lists that are not cached alone', () => {
    const qc = seed()
    applyLiveEvent(qc, 'ev', { type: 'media.ready', data: item({ id: 'n', score: 1 }) })
    expect(qc.getQueryData(keys.media('ev', 'best'))).toBeUndefined()
  })
})

describe('applyLiveEvent other events', () => {
  it('media.removed drops the item from all lists and the detail', () => {
    const qc = seed()
    applyLiveEvent(qc, 'ev', { type: 'media.removed', data: { id: 'b' } })
    expect(ids(qc, 'all')).toEqual(['a', 'c'])
    expect(ids(qc, 'videos')).toEqual([])
    applyLiveEvent(qc, 'ev', { type: 'media.removed', data: { id: 'a' } })
    expect(qc.getQueryData(keys.mediaDetail('a'))).toBeUndefined()
  })

  it('like.changed patches counts in lists and detail', () => {
    const qc = seed()
    applyLiveEvent(qc, 'ev', { type: 'like.changed', data: { media_id: 'a', like_count: 12 } })
    const data = qc.getQueryData<Data>(keys.media('ev', 'all'))
    expect(data?.pages[0]?.items[0]?.like_count).toBe(12)
    expect((qc.getQueryData(keys.mediaDetail('a')) as { like_count: number }).like_count).toBe(12)
  })

  it('media.failed marks the item', () => {
    const qc = seed()
    applyLiveEvent(qc, 'ev', { type: 'media.failed', data: { id: 'c', code: 'decode' } })
    const data = qc.getQueryData<Data>(keys.media('ev', 'mine'))
    expect(data?.pages[0]?.items[0]?.state).toBe('failed')
  })

  it('does not break structural sharing for untouched pages', () => {
    const qc = seed()
    const before = qc.getQueryData<Data>(keys.media('ev', 'all'))
    applyLiveEvent(qc, 'ev', { type: 'like.changed', data: { media_id: 'c', like_count: 3 } })
    const after = qc.getQueryData<Data>(keys.media('ev', 'all'))
    expect(after?.pages[0]).toBe(before?.pages[0])
    expect(after?.pages[1]).not.toBe(before?.pages[1])
  })
})

describe('parseLiveEvent', () => {
  it('parses known names and rejects unknown or malformed ones', () => {
    expect(parseLiveEvent('like.changed', '{"media_id":"a","like_count":2}')).toEqual({
      type: 'like.changed',
      data: { media_id: 'a', like_count: 2 },
    })
    expect(parseLiveEvent('nope', '{}')).toBeNull()
    expect(parseLiveEvent('media.ready', '{broken')).toBeNull()
  })
})
