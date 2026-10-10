import { describe, expect, it } from 'vitest'
import {
  allPartsDone,
  bytesSent,
  counts,
  initialState,
  isExpired,
  mapErrorCode,
  percentOf,
  reduce,
} from '~/lib/upload/machine'
import type { Action, FileMeta, UploadState } from '~/lib/upload/types'
import { item as gridItem } from './helpers'

function must<T>(value: T | undefined): T {
  if (value === undefined) throw new Error('expected a value')
  return value
}

const meta = (id: string, size = 1000): FileMeta => ({
  clientId: id,
  name: `${id}.jpg`,
  size,
  type: 'image/jpeg',
  lastModified: 0,
})

function run(actions: Action[], from: UploadState = initialState): UploadState {
  return actions.reduce((s, a) => reduce(s, a), from)
}

const singleInit = (clientId: string) => ({
  client_id: clientId,
  media_id: 'm'.repeat(22),
  mode: 'single' as const,
  url: 'https://s3/put',
  headers: { 'content-type': 'image/jpeg' },
  expires_at: '2999-01-01T00:00:00Z',
})

const multiInit = (clientId: string) => ({
  client_id: clientId,
  media_id: 'n'.repeat(22),
  mode: 'multipart' as const,
  parts: [1, 2, 3].map((n) => ({ part_number: n, url: `https://s3/part/${n}` })),
  part_size: 400,
  expires_at: '2999-01-01T00:00:00Z',
})

describe('item lifecycle', () => {
  it('walks picked → previewing → waiting-intent → uploading → completing → done', () => {
    let s = run([{ type: 'add', files: [meta('a')] }])
    expect(s.items.a?.status).toBe('picked')
    expect(s.queue).toBe('running')
    s = reduce(s, { type: 'preview-start', clientId: 'a' })
    expect(s.items.a?.status).toBe('previewing')
    s = reduce(s, {
      type: 'preview-ready',
      clientId: 'a',
      preview: { kind: 'icon', media: 'photo' },
    })
    expect(s.items.a?.status).toBe('waiting-intent')
    s = reduce(s, { type: 'intent-requested', clientIds: ['a'] })
    expect(s.items.a?.intentRequested).toBe(true)
    s = reduce(s, { type: 'intent-received', clientId: 'a', init: singleInit('a') })
    expect(s.items.a?.status).toBe('uploading')
    expect(s.items.a?.parts).toHaveLength(1)
    s = reduce(s, { type: 'part-progress', clientId: 'a', partNumber: 1, loaded: 500 })
    expect(percentOf(must(s.items.a))).toBe(50)
    s = reduce(s, { type: 'part-done', clientId: 'a', partNumber: 1, etag: 'x' })
    expect(allPartsDone(must(s.items.a))).toBe(true)
    s = reduce(s, { type: 'completing', clientId: 'a' })
    expect(s.items.a?.status).toBe('completing')
    expect(s.queue).toBe('draining')
    s = reduce(s, { type: 'completed', clientId: 'a', item: gridItem({ id: 'x' }) })
    expect(s.items.a?.status).toBe('done')
    expect(s.queue).toBe('done')
    expect(s.finishedAt).not.toBeNull()
    expect(counts(s)).toEqual({ done: 1, failed: 0, total: 1, succeeded: 1 })
  })

  it('splits multipart intents into sized parts', () => {
    const s = run([
      { type: 'add', files: [meta('a', 1000)] },
      { type: 'preview-ready', clientId: 'a', preview: { kind: 'icon', media: 'photo' } },
      { type: 'intent-received', clientId: 'a', init: multiInit('a') },
    ])
    expect(s.items.a?.parts.map((p) => p.size)).toEqual([400, 400, 200])
    const after = reduce(s, { type: 'part-done', clientId: 'a', partNumber: 2, etag: 'e2' })
    expect(bytesSent(must(after.items.a))).toBe(400)
    expect(percentOf(must(after.items.a))).toBe(40)
  })

  it('finishes duplicates immediately', () => {
    const s = run([
      { type: 'add', files: [meta('a')] },
      { type: 'preview-ready', clientId: 'a', preview: { kind: 'icon', media: 'photo' } },
      {
        type: 'intent-received',
        clientId: 'a',
        init: {
          client_id: 'a',
          media_id: 'd'.repeat(22),
          mode: 'duplicate',
          duplicate_of: 'o'.repeat(22),
          expires_at: '',
        },
      },
    ])
    expect(s.items.a?.status).toBe('done')
    expect(s.items.a?.duplicateOf).toBe('o'.repeat(22))
    expect(counts(s).succeeded).toBe(0)
  })
})

describe('failures and retries', () => {
  const uploading = run([
    { type: 'add', files: [meta('a')] },
    { type: 'preview-ready', clientId: 'a', preview: { kind: 'icon', media: 'photo' } },
    { type: 'intent-received', clientId: 'a', init: singleInit('a') },
  ])

  it('retries a part up to 6 attempts, then fails', () => {
    let s = uploading
    for (let i = 1; i <= 5; i++) {
      s = reduce(s, { type: 'part-failed', clientId: 'a', partNumber: 1, httpStatus: 0 })
      expect(s.items.a?.status).toBe('uploading')
      expect(s.items.a?.parts[0]?.attempts).toBe(i)
    }
    s = reduce(s, { type: 'part-failed', clientId: 'a', partNumber: 1, httpStatus: 0 })
    expect(s.items.a?.status).toBe('failed')
    expect(s.items.a?.error).toBe('network')
  })

  it('flags needsRefresh on 403 and clears it when fresh URLs arrive', () => {
    let s = reduce(uploading, {
      type: 'part-failed',
      clientId: 'a',
      partNumber: 1,
      httpStatus: 403,
    })
    expect(s.items.a?.needsRefresh).toBe(true)
    s = reduce(s, {
      type: 'urls-refreshed',
      clientId: 'a',
      status: {
        media_id: 'm'.repeat(22),
        mode: 'single',
        url: 'https://s3/fresh',
        received_parts: [],
        parts: [],
        expires_at: '2999-01-01T00:00:00Z',
      },
    })
    expect(s.items.a?.needsRefresh).toBe(false)
    expect(s.items.a?.parts[0]?.url).toBe('https://s3/fresh')
  })

  it('marks already received parts when refreshing a multipart upload', () => {
    let s = run([
      { type: 'add', files: [meta('a', 1000)] },
      { type: 'preview-ready', clientId: 'a', preview: { kind: 'icon', media: 'photo' } },
      { type: 'intent-received', clientId: 'a', init: multiInit('a') },
    ])
    s = reduce(s, {
      type: 'urls-refreshed',
      clientId: 'a',
      status: {
        media_id: 'n'.repeat(22),
        mode: 'multipart',
        received_parts: [1],
        parts: [2, 3].map((n) => ({ part_number: n, url: `https://s3/fresh/${n}` })),
        part_size: 400,
        expires_at: '2999-01-01T00:00:00Z',
      },
    })
    expect(s.items.a?.parts.map((p) => [p.partNumber, p.etag !== null, p.url])).toEqual([
      [1, true, 'https://s3/part/1'],
      [2, false, 'https://s3/fresh/2'],
      [3, false, 'https://s3/fresh/3'],
    ])
  })

  it('maps non-retryable intent errors to failed and keeps retryable ones waiting', () => {
    const waiting = run([
      { type: 'add', files: [meta('a'), meta('b')] },
      { type: 'preview-ready', clientId: 'a', preview: { kind: 'icon', media: 'photo' } },
      { type: 'preview-ready', clientId: 'b', preview: { kind: 'icon', media: 'photo' } },
      { type: 'intent-requested', clientIds: ['a', 'b'] },
    ])
    const hard = reduce(waiting, {
      type: 'intent-failed',
      clientIds: ['a'],
      code: 'too_large',
      retryable: false,
    })
    expect(hard.items.a?.status).toBe('failed')
    expect(hard.items.a?.error).toBe('too_large')
    const soft = reduce(waiting, {
      type: 'intent-failed',
      clientIds: ['b'],
      code: 'network',
      retryable: true,
    })
    expect(soft.items.b?.status).toBe('waiting-intent')
    expect(soft.items.b?.intentRequested).toBe(false)
  })

  it('retry returns to waiting-intent without a media id and to uploading with one', () => {
    const noIntent = run([
      { type: 'add', files: [meta('a')] },
      { type: 'preview-ready', clientId: 'a', preview: { kind: 'icon', media: 'photo' } },
      { type: 'intent-failed', clientIds: ['a'], code: 'forbidden', retryable: false },
    ])
    expect(reduce(noIntent, { type: 'retry', clientId: 'a' }).items.a?.status).toBe(
      'waiting-intent',
    )

    const failed = reduce(uploading, { type: 'failed', clientId: 'a', code: 'network' })
    const retried = reduce(failed, { type: 'retry', clientId: 'a' })
    expect(retried.items.a?.status).toBe('uploading')
    expect(retried.items.a?.needsRefresh).toBe(true)
    expect(retried.items.a?.parts[0]?.attempts).toBe(0)
  })

  it('cancel is terminal and remove drops the item', () => {
    const cancelled = reduce(uploading, { type: 'cancel', clientId: 'a' })
    expect(cancelled.items.a?.status).toBe('cancelled')
    expect(
      reduce(cancelled, { type: 'completed', clientId: 'a', item: gridItem({ id: 'x' }) }).items.a
        ?.status,
    ).toBe('done')
    expect(counts(cancelled).total).toBe(0)
    const removed = reduce(cancelled, { type: 'remove', clientId: 'a' })
    expect(removed.order).toEqual([])
    expect(removed.queue).toBe('idle')
  })
})

describe('offline and online', () => {
  it('pauses uploading items offline and resumes them online with a refresh', () => {
    let s = run([
      { type: 'add', files: [meta('a'), meta('b')] },
      { type: 'preview-ready', clientId: 'a', preview: { kind: 'icon', media: 'photo' } },
      { type: 'preview-ready', clientId: 'b', preview: { kind: 'icon', media: 'photo' } },
      { type: 'intent-received', clientId: 'a', init: singleInit('a') },
      { type: 'part-progress', clientId: 'a', partNumber: 1, loaded: 300 },
      { type: 'intent-requested', clientIds: ['b'] },
    ])
    s = reduce(s, { type: 'offline' })
    expect(s.queue).toBe('paused-offline')
    expect(s.items.a?.status).toBe('paused')
    expect(s.items.a?.parts[0]?.loaded).toBe(0)
    expect(s.items.b?.status).toBe('waiting-intent')
    expect(s.items.b?.intentRequested).toBe(false)
    // An in-flight failure while offline keeps the item paused and does not count against attempts limit.
    s = reduce(s, { type: 'part-failed', clientId: 'a', partNumber: 1, httpStatus: 0 })
    expect(s.items.a?.status).toBe('paused')
    s = reduce(s, { type: 'online' })
    expect(s.queue).toBe('running')
    expect(s.items.a?.status).toBe('uploading')
    expect(s.items.a?.needsRefresh).toBe(true)
  })

  it('intents that arrive while offline land in paused', () => {
    const s = run([
      { type: 'add', files: [meta('a')] },
      { type: 'preview-ready', clientId: 'a', preview: { kind: 'icon', media: 'photo' } },
      { type: 'offline' },
      { type: 'intent-received', clientId: 'a', init: singleInit('a') },
    ])
    expect(s.items.a?.status).toBe('paused')
  })
})

describe('queue status and misc', () => {
  it('is idle without items and done when everything is terminal', () => {
    expect(initialState.queue).toBe('idle')
    const s = run([
      { type: 'add', files: [meta('a')] },
      { type: 'preview-ready', clientId: 'a', preview: { kind: 'icon', media: 'photo' } },
      { type: 'intent-failed', clientIds: ['a'], code: 'too_large', retryable: false },
    ])
    expect(s.queue).toBe('done')
    const more = reduce(s, { type: 'add', files: [meta('b')] })
    expect(more.queue).toBe('running')
    expect(more.finishedAt).toBeNull()
  })

  it('restores manifest items as uploading with a refresh or waiting-intent', () => {
    const base = must(run([{ type: 'add', files: [meta('x')] }]).items.x)
    const s = reduce(initialState, {
      type: 'restore',
      items: [
        { ...base, clientId: 'r1', mediaId: 'm'.repeat(22), mode: 'single' },
        { ...base, clientId: 'r2' },
      ],
    })
    expect(s.items.r1?.status).toBe('uploading')
    expect(s.items.r1?.needsRefresh).toBe(true)
    expect(s.items.r2?.status).toBe('waiting-intent')
  })

  it('isExpired and mapErrorCode', () => {
    const base = must(run([{ type: 'add', files: [meta('x')] }]).items.x)
    expect(isExpired({ ...base, expiresAt: '2000-01-01T00:00:00Z' })).toBe(true)
    expect(isExpired({ ...base, expiresAt: '2999-01-01T00:00:00Z' })).toBe(false)
    expect(isExpired(base)).toBe(false)
    expect(mapErrorCode(413)).toBe('too_large')
    expect(mapErrorCode(400, 'unsupported_media')).toBe('unsupported_media')
    expect(mapErrorCode(403)).toBe('forbidden')
    expect(mapErrorCode(0)).toBe('network')
    expect(mapErrorCode(503)).toBe('network')
    expect(mapErrorCode(400)).toBe('unknown')
  })

  it('ignores actions for unknown items', () => {
    expect(reduce(initialState, { type: 'retry', clientId: 'nope' })).toBe(initialState)
  })
})
