import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CompletedPart, GridItem, UploadFile, UploadInit, UploadStatus } from '~/lib/api/types'
import { type UploadApi, UploadQueue } from '~/lib/upload/queue'
import { TransportError } from '~/lib/upload/transport'
import { item as gridItem } from './helpers'

class FakeFile extends Blob {
  readonly name: string
  readonly lastModified = 0
  constructor(name: string, size: number, type = 'image/jpeg') {
    super([new Uint8Array(size)], { type })
    this.name = name
  }
}

interface PutCall {
  url: string
  size: number
  resolve: (etag?: string | null) => void
  reject: (status: number) => void
}

function fakeApi(overrides: Partial<UploadApi> = {}) {
  const calls = {
    intents: [] as UploadFile[][],
    completes: [] as Array<{ id: string; parts?: CompletedPart[] }>,
    statuses: [] as string[],
  }
  const api: UploadApi = {
    async createIntents(files) {
      calls.intents.push(files)
      return files.map<UploadInit>((f) =>
        f.size > 1000
          ? {
              client_id: f.client_id,
              media_id: `media-${f.client_id}`.padEnd(22, '0'),
              mode: 'multipart',
              parts: [1, 2].map((n) => ({ part_number: n, url: `https://s3/${f.client_id}/${n}` })),
              part_size: Math.ceil(f.size / 2),
              expires_at: '2999-01-01T00:00:00Z',
            }
          : {
              client_id: f.client_id,
              media_id: `media-${f.client_id}`.padEnd(22, '0'),
              mode: 'single',
              url: `https://s3/${f.client_id}`,
              headers: { 'content-type': f.type },
              expires_at: '2999-01-01T00:00:00Z',
            },
      )
    },
    async getStatus(mediaId): Promise<UploadStatus> {
      calls.statuses.push(mediaId)
      return {
        media_id: mediaId,
        mode: 'single',
        url: `https://s3/fresh/${mediaId}`,
        received_parts: [],
        parts: [],
        expires_at: '2999-01-01T00:00:00Z',
      }
    },
    async complete(id, parts): Promise<GridItem> {
      calls.completes.push({ id, parts })
      return gridItem({ id, state: 'queued', processing: true })
    },
    async abort() {},
    ...overrides,
  }
  return { api, calls }
}

function setup(
  apiOverrides: Partial<UploadApi> = {},
  opts: Partial<ConstructorParameters<typeof UploadQueue>[0]> = {},
) {
  const puts: PutCall[] = []
  const done: GridItem[] = []
  const { api, calls } = fakeApi(apiOverrides)
  const queue = new UploadQueue({
    slug: 'ev',
    api,
    onDone: (i) => done.push(i),
    preview: async () => ({ kind: 'icon', media: 'photo' }),
    backoff: () => 10,
    put: (url, blob, _headers, onProgress) => {
      let abort = () => {}
      const promise = new Promise<{ etag: string | null }>((resolve, reject) => {
        puts.push({
          url,
          size: blob.size,
          resolve: (etag = 'etag') => {
            onProgress(blob.size)
            resolve({ etag })
          },
          reject: (status) => reject(new TransportError(status)),
        })
        abort = () => reject(new TransportError(-1))
      })
      return { promise, abort }
    },
    ...opts,
  })
  return { queue, puts, done, calls }
}

const flush = async (ms = 0) => {
  await vi.advanceTimersByTimeAsync(ms)
  await vi.advanceTimersByTimeAsync(0)
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('UploadQueue', () => {
  it('batches intents after the debounce and uploads with 3 concurrent PUTs', async () => {
    const { queue, puts, done, calls } = setup()
    queue.addFiles(
      Array.from({ length: 5 }, (_, i) => new FakeFile(`${i}.jpg`, 100) as unknown as File),
    )
    await flush(149)
    expect(calls.intents).toHaveLength(0)
    await flush(1)
    expect(calls.intents).toHaveLength(1)
    expect(calls.intents[0]).toHaveLength(5)
    await flush()
    expect(puts).toHaveLength(3)
    puts[0]?.resolve()
    await flush()
    expect(puts).toHaveLength(4)
    for (const p of puts.slice(1)) p.resolve()
    await flush()
    expect(puts).toHaveLength(5)
    puts[4]?.resolve()
    await flush()
    expect(calls.completes).toHaveLength(5)
    expect(done).toHaveLength(5)
    expect(queue.getState().queue).toBe('done')
  })

  it('splits more than 20 files into several intent requests', async () => {
    const { queue, calls } = setup()
    queue.addFiles(
      Array.from({ length: 23 }, (_, i) => new FakeFile(`${i}.jpg`, 10) as unknown as File),
    )
    await flush(150)
    await flush(150)
    expect(calls.intents.map((b) => b.length)).toEqual([20, 3])
  })

  it('calls ensureGuest once before the first intent when anonymous', async () => {
    const ensureGuest = vi.fn(async () => ({ guest_id: 'g' }))
    const { queue, calls } = setup({}, { ensureGuest, needsGuest: true })
    queue.addFiles([new FakeFile('a.jpg', 10) as unknown as File])
    await flush(150)
    queue.addFiles([new FakeFile('b.jpg', 10) as unknown as File])
    await flush(150)
    expect(ensureGuest).toHaveBeenCalledTimes(1)
    expect(calls.intents).toHaveLength(2)
  })

  it('sends multipart parts as slices and completes with etags', async () => {
    const { queue, puts, calls } = setup()
    queue.addFiles([new FakeFile('big.jpg', 3000) as unknown as File])
    await flush(150)
    expect(puts.map((p) => p.size)).toEqual([1500, 1500])
    puts[0]?.resolve('e1')
    puts[1]?.resolve('e2')
    await flush()
    expect(calls.completes[0]?.parts).toEqual([
      { part_number: 1, etag: 'e1' },
      { part_number: 2, etag: 'e2' },
    ])
  })

  it('retries a failed part after backoff and refreshes URLs after a 403', async () => {
    const { queue, puts, calls } = setup()
    queue.addFiles([new FakeFile('a.jpg', 10) as unknown as File])
    await flush(150)
    puts[0]?.reject(500)
    await flush(10)
    expect(puts).toHaveLength(2)
    expect(puts[1]?.url).toBe(puts[0]?.url)
    puts[1]?.reject(403)
    await flush(10)
    expect(calls.statuses).toHaveLength(1)
    await flush()
    expect(puts).toHaveLength(3)
    expect(puts[2]?.url).toMatch(/fresh/)
    puts[2]?.resolve()
    await flush()
    expect(queue.getState().items[Object.keys(queue.getState().items)[0] ?? '']?.status).toBe(
      'done',
    )
  })

  it('gives up after six attempts and lets the user retry', async () => {
    const { queue, puts } = setup()
    queue.addFiles([new FakeFile('a.jpg', 10) as unknown as File])
    await flush(150)
    for (let i = 0; i < 6; i++) {
      puts[i]?.reject(0)
      await flush(10)
    }
    const id = Object.keys(queue.getState().items)[0] ?? ''
    expect(queue.getState().items[id]?.status).toBe('failed')
    expect(puts).toHaveLength(6)
    queue.retry(id)
    await flush()
    expect(queue.getState().items[id]?.status).toBe('uploading')
  })

  it('pauses offline, aborts in-flight PUTs, and resumes online with fresh URLs', async () => {
    const { queue, puts, calls } = setup()
    queue.addFiles([new FakeFile('a.jpg', 10) as unknown as File])
    await flush(150)
    expect(puts).toHaveLength(1)
    queue.setOnline(false)
    await flush()
    expect(queue.getState().queue).toBe('paused-offline')
    expect(puts).toHaveLength(1)
    queue.setOnline(true)
    await flush()
    expect(calls.statuses).toHaveLength(1)
    expect(puts).toHaveLength(2)
  })

  it('marks non-retryable intent errors as failed with the code', async () => {
    const { queue } = setup({
      createIntents: async () => {
        throw Object.assign(new Error('too large'), { status: 413, code: 'too_large' })
      },
    })
    queue.addFiles([new FakeFile('a.jpg', 10) as unknown as File])
    await flush(150)
    const id = Object.keys(queue.getState().items)[0] ?? ''
    expect(queue.getState().items[id]?.status).toBe('failed')
    expect(queue.getState().items[id]?.error).toBe('too_large')
  })

  it('cancel aborts the upload on the server', async () => {
    const abort = vi.fn(async () => {})
    const { queue, puts } = setup({ abort })
    queue.addFiles([new FakeFile('a.jpg', 10) as unknown as File])
    await flush(150)
    expect(puts).toHaveLength(1)
    const id = Object.keys(queue.getState().items)[0] ?? ''
    queue.cancel(id)
    await flush()
    expect(abort).toHaveBeenCalledTimes(1)
    expect(queue.getState().items[id]?.status).toBe('cancelled')
  })
})
