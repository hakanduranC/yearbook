import type { CompletedPart, GridItem, UploadFile, UploadInit, UploadStatus } from '~/lib/api/types'
import { backoffMs } from './backoff'
import {
  allPartsDone,
  counts,
  initialState,
  isExpired,
  isTerminal,
  itemsOf,
  mapErrorCode,
  reduce,
} from './machine'
import { itemFromRecord, type Manifest, noopManifest } from './manifest'
import { makePreview, mediaKind, revokePreview } from './preview'
import { type PutHandle, putBlob, TransportError } from './transport'
import {
  type Action,
  type FileMeta,
  INTENT_BATCH,
  INTENT_DEBOUNCE_MS,
  MAX_CONCURRENT,
  type UploadItemState,
  type UploadState,
} from './types'

export interface UploadApi {
  createIntents(files: UploadFile[]): Promise<UploadInit[]>
  getStatus(mediaId: string): Promise<UploadStatus>
  complete(mediaId: string, parts?: CompletedPart[]): Promise<GridItem>
  abort(mediaId: string): Promise<void>
}

export type TimerHandle = ReturnType<typeof globalThis.setTimeout>

export interface QueueOptions {
  slug: string
  api: UploadApi
  /** Called once before the first intent when the viewer has no guest cookie yet. */
  ensureGuest?: () => Promise<unknown>
  needsGuest?: boolean
  onDone?: (item: GridItem) => void
  manifest?: Manifest
  put?: typeof putBlob
  preview?: typeof makePreview
  concurrency?: number
  intentDebounceMs?: number
  backoff?: (attempt: number) => number
  setTimeout?: (fn: () => void, ms: number) => TimerHandle
  clearTimeout?: (handle: TimerHandle) => void
  now?: () => number
}

interface ApiLikeError {
  status?: number
  code?: string
}

function errorInfo(err: unknown): { status: number; code?: string } {
  const e = err as ApiLikeError
  return {
    status: typeof e?.status === 'number' ? e.status : 0,
    code: typeof e?.code === 'string' ? e.code : undefined,
  }
}

/**
 * Drives the pure reducer: previews, batched intents, 3 concurrent PUTs with retry and URL refresh,
 * completion, manifest persistence and online/offline handling.
 */
export class UploadQueue {
  private state: UploadState = initialState
  private readonly listeners = new Set<() => void>()
  private readonly files = new Map<string, Blob>()
  private readonly inflight = new Map<string, PutHandle>()
  private readonly busy = new Set<string>()
  private readonly waits = new Map<string, TimerHandle>()
  private intentTimer: TimerHandle | null = null
  private guestPromise: Promise<unknown> | null = null
  private needsGuest: boolean
  private scheduled = false
  private readonly opts: Required<
    Pick<
      QueueOptions,
      | 'concurrency'
      | 'intentDebounceMs'
      | 'backoff'
      | 'setTimeout'
      | 'clearTimeout'
      | 'now'
      | 'put'
      | 'preview'
      | 'manifest'
    >
  > &
    QueueOptions

  constructor(options: QueueOptions) {
    this.opts = {
      concurrency: MAX_CONCURRENT,
      intentDebounceMs: INTENT_DEBOUNCE_MS,
      backoff: backoffMs,
      setTimeout: (fn: () => void, ms: number) => globalThis.setTimeout(fn, ms),
      clearTimeout: (handle: TimerHandle) => globalThis.clearTimeout(handle),
      now: () => Date.now(),
      put: putBlob,
      preview: makePreview,
      manifest: noopManifest,
      ...options,
    }
    this.needsGuest = options.needsGuest ?? false
    this.state = {
      ...initialState,
      online: typeof navigator === 'undefined' ? true : navigator.onLine !== false,
    }
  }

  get slug(): string {
    return this.opts.slug
  }

  getState(): UploadState {
    return this.state
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  setNeedsGuest(value: boolean) {
    this.needsGuest = value
  }

  dispatch(action: Action) {
    const next = reduce(this.state, action)
    if (next === this.state) return
    this.state = next
    for (const l of this.listeners) l()
    this.schedule()
  }

  addFiles(files: File[]) {
    const metas: FileMeta[] = []
    for (const file of files) {
      const clientId = `${this.opts.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
      this.files.set(clientId, file)
      metas.push({
        clientId,
        name: file.name,
        size: file.size,
        type: file.type || guessType(file.name),
        lastModified: file.lastModified,
      })
    }
    if (metas.length) this.dispatch({ type: 'add', files: metas })
  }

  retry(clientId: string) {
    this.dispatch({ type: 'retry', clientId })
  }

  cancel(clientId: string) {
    const item = this.state.items[clientId]
    this.abortItem(clientId)
    this.dispatch({ type: 'cancel', clientId })
    if (item?.mediaId && item.mode !== 'duplicate' && item.status !== 'done') {
      this.opts.api.abort(item.mediaId).catch(() => {})
    }
    void this.opts.manifest.remove(clientId)
  }

  remove(clientId: string) {
    const item = this.state.items[clientId]
    this.abortItem(clientId)
    revokePreview(item?.preview ?? null)
    this.files.delete(clientId)
    this.dispatch({ type: 'remove', clientId })
    void this.opts.manifest.remove(clientId)
  }

  setOnline(online: boolean) {
    if (online === this.state.online) return
    if (!online) {
      for (const key of [...this.inflight.keys()]) {
        this.inflight.get(key)?.abort()
        this.inflight.delete(key)
      }
    }
    this.dispatch({ type: online ? 'online' : 'offline' })
  }

  acknowledgeFinished() {
    this.dispatch({ type: 'acknowledge-finished' })
  }

  /** Counts manifest entries that can be resumed (those whose blob was stored). */
  async resumable(): Promise<number> {
    const records = await this.opts.manifest.listOpen(this.opts.slug)
    return records.filter((r) => r.blob && !this.state.items[r.clientId]).length
  }

  /** Restores manifest entries into the queue; entries without a blob are dropped. */
  async resume(): Promise<number> {
    const records = await this.opts.manifest.listOpen(this.opts.slug)
    const items: UploadItemState[] = []
    for (const record of records) {
      if (this.state.items[record.clientId]) continue
      if (!record.blob) {
        void this.opts.manifest.remove(record.clientId)
        continue
      }
      this.files.set(record.clientId, record.blob)
      items.push(itemFromRecord(record))
    }
    if (items.length) this.dispatch({ type: 'restore', items })
    return items.length
  }

  async discardResumable(): Promise<void> {
    await this.opts.manifest.clear(this.opts.slug)
  }

  /** Aborts everything in flight. Used on unmount of the owning page when the user confirms leaving. */
  destroy() {
    for (const handle of this.inflight.values()) handle.abort()
    this.inflight.clear()
    for (const timer of this.waits.values()) this.opts.clearTimeout(timer)
    this.waits.clear()
    if (this.intentTimer) this.opts.clearTimeout(this.intentTimer)
    for (const item of itemsOf(this.state)) revokePreview(item.preview)
  }

  // Scheduling

  private schedule() {
    if (this.scheduled) return
    this.scheduled = true
    queueMicrotask(() => {
      this.scheduled = false
      this.tick()
    })
  }

  private tick() {
    const items = itemsOf(this.state)
    for (const item of items) {
      if (item.status === 'picked' && !this.busy.has(`preview:${item.clientId}`))
        this.startPreview(item)
    }
    if (this.state.online) {
      const waiting = items.filter(
        (i) => i.status === 'waiting-intent' && !i.intentRequested && !this.waits.has(i.clientId),
      )
      if (waiting.length && !this.intentTimer) {
        this.intentTimer = this.opts.setTimeout(() => {
          this.intentTimer = null
          void this.requestIntents()
        }, this.opts.intentDebounceMs)
      }
      for (const item of items) {
        if (item.status !== 'uploading') continue
        if (allPartsDone(item) && !this.hasInflight(item.clientId)) {
          this.startComplete(item)
          continue
        }
        if (
          (item.needsRefresh || isExpired(item, this.opts.now())) &&
          !this.busy.has(`refresh:${item.clientId}`)
        ) {
          if (!this.hasInflight(item.clientId)) this.startRefresh(item)
          continue
        }
        for (const part of item.parts) {
          if (this.inflight.size >= this.opts.concurrency) break
          if (part.etag !== null) continue
          const key = `${item.clientId}:${part.partNumber}`
          if (this.inflight.has(key) || this.waits.has(key)) continue
          if (!part.url) continue
          this.startPut(item, part.partNumber)
        }
      }
    }
  }

  private hasInflight(clientId: string): boolean {
    for (const key of this.inflight.keys()) if (key.startsWith(`${clientId}:`)) return true
    for (const key of this.waits.keys()) if (key.startsWith(`${clientId}:`)) return true
    return false
  }

  private abortItem(clientId: string) {
    for (const [key, handle] of this.inflight) {
      if (key.startsWith(`${clientId}:`)) {
        handle.abort()
        this.inflight.delete(key)
      }
    }
    for (const [key, timer] of this.waits) {
      if (key === clientId || key.startsWith(`${clientId}:`)) {
        this.opts.clearTimeout(timer)
        this.waits.delete(key)
      }
    }
  }

  private startPreview(item: UploadItemState) {
    const key = `preview:${item.clientId}`
    this.busy.add(key)
    this.dispatch({ type: 'preview-start', clientId: item.clientId })
    const blob = this.files.get(item.clientId)
    const run = blob
      ? this.opts.preview(blob, item.type, item.name)
      : Promise.resolve({ kind: 'icon' as const, media: mediaKind(item.type, item.name) })
    run
      .catch(() => ({ kind: 'icon' as const, media: mediaKind(item.type, item.name) }))
      .then((preview) => {
        this.busy.delete(key)
        this.dispatch({ type: 'preview-ready', clientId: item.clientId, preview })
      })
  }

  private async ensureGuestOnce(): Promise<void> {
    if (!this.needsGuest || !this.opts.ensureGuest) return
    if (!this.guestPromise) {
      this.guestPromise = this.opts.ensureGuest().then(
        () => {
          this.needsGuest = false
        },
        (err) => {
          this.guestPromise = null
          throw err
        },
      )
    }
    await this.guestPromise
  }

  private async requestIntents() {
    const batch = itemsOf(this.state)
      .filter(
        (i) => i.status === 'waiting-intent' && !i.intentRequested && !this.waits.has(i.clientId),
      )
      .slice(0, INTENT_BATCH)
    if (batch.length === 0) return
    const ids = batch.map((i) => i.clientId)
    this.dispatch({ type: 'intent-requested', clientIds: ids })
    try {
      await this.ensureGuestOnce()
      const inits = await this.opts.api.createIntents(
        batch.map((i) => ({
          client_id: i.clientId,
          name: i.name,
          size: i.size,
          type: i.type,
          last_modified: new Date(i.lastModified).toISOString(),
        })),
      )
      const byClient = new Map(inits.map((init) => [init.client_id, init]))
      for (const id of ids) {
        const init = byClient.get(id)
        if (init) {
          this.dispatch({ type: 'intent-received', clientId: id, init })
          const item = this.state.items[id]
          if (item && item.mode !== 'duplicate') void this.persist(item)
        } else {
          this.dispatch({
            type: 'intent-failed',
            clientIds: [id],
            code: 'unknown',
            retryable: false,
          })
        }
      }
    } catch (err) {
      const { status, code } = errorInfo(err)
      const mapped = mapErrorCode(status, code)
      const retryable = mapped === 'network' || status === 429
      this.dispatch({ type: 'intent-failed', clientIds: ids, code: mapped, retryable })
      if (retryable) {
        const delay = this.opts.backoff(1)
        for (const id of ids) {
          const timer = this.opts.setTimeout(() => {
            this.waits.delete(id)
            this.schedule()
          }, delay)
          this.waits.set(id, timer)
        }
      }
    }
    // More may be waiting (batches over 20 files).
    this.schedule()
  }

  private startPut(item: UploadItemState, partNumber: number) {
    const part = item.parts.find((p) => p.partNumber === partNumber)
    const blob = this.files.get(item.clientId)
    if (!part || !blob) {
      this.dispatch({ type: 'failed', clientId: item.clientId, code: 'unknown' })
      return
    }
    const key = `${item.clientId}:${partNumber}`
    const chunk =
      item.mode === 'multipart'
        ? blob.slice((partNumber - 1) * item.partSize, (partNumber - 1) * item.partSize + part.size)
        : blob
    const handle = this.opts.put(
      part.url,
      chunk,
      item.mode === 'single' ? item.headers : {},
      (loaded) =>
        this.dispatch({ type: 'part-progress', clientId: item.clientId, partNumber, loaded }),
    )
    this.inflight.set(key, handle)
    handle.promise.then(
      ({ etag }) => {
        this.inflight.delete(key)
        this.dispatch({ type: 'part-done', clientId: item.clientId, partNumber, etag })
        const current = this.state.items[item.clientId]
        if (current) void this.persist(current)
      },
      (err: unknown) => {
        this.inflight.delete(key)
        const status = err instanceof TransportError ? err.status : 0
        if (status === -1) return // aborted on purpose
        const before = this.state.items[item.clientId]
        this.dispatch({
          type: 'part-failed',
          clientId: item.clientId,
          partNumber,
          httpStatus: status,
        })
        const after = this.state.items[item.clientId]
        if (after && after.status === 'uploading' && before) {
          const attempts = after.parts.find((p) => p.partNumber === partNumber)?.attempts ?? 1
          const timer = this.opts.setTimeout(() => {
            this.waits.delete(key)
            this.schedule()
          }, this.opts.backoff(attempts))
          this.waits.set(key, timer)
        }
      },
    )
  }

  private startRefresh(item: UploadItemState) {
    const key = `refresh:${item.clientId}`
    if (!item.mediaId) return
    this.busy.add(key)
    this.opts.api.getStatus(item.mediaId).then(
      (status) => {
        this.busy.delete(key)
        this.dispatch({ type: 'urls-refreshed', clientId: item.clientId, status })
      },
      (err: unknown) => {
        this.busy.delete(key)
        const { status, code } = errorInfo(err)
        const mapped = mapErrorCode(status, code)
        if (mapped === 'network') {
          const timer = this.opts.setTimeout(() => {
            this.waits.delete(`${item.clientId}:refresh`)
            this.schedule()
          }, this.opts.backoff(1))
          this.waits.set(`${item.clientId}:refresh`, timer)
        } else {
          this.dispatch({
            type: 'refresh-failed',
            clientId: item.clientId,
            code: mapped === 'unknown' ? 'network' : mapped,
          })
        }
      },
    )
  }

  private startComplete(item: UploadItemState) {
    if (!item.mediaId) return
    const key = `complete:${item.clientId}`
    if (this.busy.has(key)) return
    this.busy.add(key)
    this.dispatch({ type: 'completing', clientId: item.clientId })
    const parts: CompletedPart[] | undefined =
      item.mode === 'multipart'
        ? item.parts.map((p) => ({ part_number: p.partNumber, etag: p.etag ?? '' }))
        : undefined
    this.opts.api.complete(item.mediaId, parts).then(
      (grid) => {
        this.busy.delete(key)
        this.dispatch({ type: 'completed', clientId: item.clientId, item: grid })
        void this.opts.manifest.remove(item.clientId)
        this.files.delete(item.clientId)
        this.opts.onDone?.(grid)
      },
      (err: unknown) => {
        this.busy.delete(key)
        const { status, code } = errorInfo(err)
        const mapped = mapErrorCode(status, code)
        this.dispatch({
          type: 'failed',
          clientId: item.clientId,
          code: mapped === 'unknown' ? 'network' : mapped,
        })
      },
    )
  }

  private async persist(item: UploadItemState) {
    if (isTerminal(item.status)) return
    try {
      await this.opts.manifest.save(this.opts.slug, item, this.files.get(item.clientId) ?? null)
    } catch {
      // Storage may be unavailable (private mode); uploads still work without resume.
    }
  }

  summary() {
    return counts(this.state)
  }
}

function guessType(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase()
  switch (ext) {
    case 'jpg':
    case 'jpeg':
      return 'image/jpeg'
    case 'png':
      return 'image/png'
    case 'heic':
      return 'image/heic'
    case 'heif':
      return 'image/heif'
    case 'webp':
      return 'image/webp'
    case 'avif':
      return 'image/avif'
    case 'mp4':
      return 'video/mp4'
    case 'mov':
      return 'video/quicktime'
    default:
      return 'application/octet-stream'
  }
}
