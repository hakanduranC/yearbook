import type { UploadInit, UploadStatus } from '~/lib/api/types'
import {
  type Action,
  type ErrorCode,
  type FileMeta,
  type ItemStatus,
  MAX_PART_ATTEMPTS,
  type PartState,
  type QueueStatus,
  type UploadItemState,
  type UploadState,
} from './types'

export const initialState: UploadState = {
  items: {},
  order: [],
  online: true,
  queue: 'idle',
  finishedAt: null,
}

const TERMINAL: ReadonlySet<ItemStatus> = new Set(['done', 'failed', 'cancelled'])
const ACTIVE: ReadonlySet<ItemStatus> = new Set([
  'picked',
  'previewing',
  'waiting-intent',
  'uploading',
  'paused',
])

export function isTerminal(status: ItemStatus): boolean {
  return TERMINAL.has(status)
}

export function newItem(meta: FileMeta): UploadItemState {
  return {
    ...meta,
    status: 'picked',
    preview: null,
    mediaId: null,
    mode: null,
    headers: {},
    parts: [],
    partSize: 0,
    expiresAt: null,
    duplicateOf: null,
    intentRequested: false,
    needsRefresh: false,
    error: null,
    result: null,
    restored: false,
  }
}

export function deriveQueue(state: UploadState): QueueStatus {
  const items = state.order.map((id) => state.items[id]).filter((i): i is UploadItemState => !!i)
  if (items.length === 0) return 'idle'
  const open = items.filter((i) => !TERMINAL.has(i.status))
  if (open.length === 0) return 'done'
  if (!state.online) return 'paused-offline'
  if (open.some((i) => ACTIVE.has(i.status))) return 'running'
  return 'draining'
}

function partsFromInit(init: UploadInit, size: number): { parts: PartState[]; partSize: number } {
  if (init.mode === 'multipart' && init.parts && init.parts.length > 0) {
    const partSize = init.part_size ?? Math.ceil(size / init.parts.length)
    const parts = init.parts.map((p) => ({
      partNumber: p.part_number,
      url: p.url,
      size: Math.max(0, Math.min(partSize, size - (p.part_number - 1) * partSize)),
      loaded: 0,
      etag: null,
      attempts: 0,
    }))
    return { parts, partSize }
  }
  return {
    parts: [{ partNumber: 1, url: init.url ?? '', size, loaded: 0, etag: null, attempts: 0 }],
    partSize: size,
  }
}

function mergeStatus(item: UploadItemState, status: UploadStatus): UploadItemState {
  const received = new Set(status.received_parts)
  if (status.mode === 'single') {
    const existing = item.parts[0]
    const done = received.has(1) || (existing?.etag !== null && existing !== undefined)
    return {
      ...item,
      needsRefresh: false,
      expiresAt: status.expires_at,
      parts: [
        {
          partNumber: 1,
          url: status.url ?? existing?.url ?? '',
          size: item.size,
          loaded: done ? item.size : 0,
          etag: done ? (existing?.etag ?? 'received') : null,
          attempts: existing?.attempts ?? 0,
        },
      ],
    }
  }
  const byNumber = new Map(item.parts.map((p) => [p.partNumber, p]))
  const partSize = status.part_size ?? item.partSize
  const parts: PartState[] = (status.parts ?? []).map((p) => {
    const prev = byNumber.get(p.part_number)
    const done = received.has(p.part_number) || (prev?.etag ?? null) !== null
    const size =
      prev?.size ?? Math.max(0, Math.min(partSize, item.size - (p.part_number - 1) * partSize))
    return {
      partNumber: p.part_number,
      url: p.url,
      size,
      loaded: done ? size : 0,
      etag: done ? (prev?.etag ?? 'received') : null,
      attempts: prev?.attempts ?? 0,
    }
  })
  // Parts the server already has are not re-listed: keep or synthesize them as done.
  for (const n of received) {
    if (parts.some((p) => p.partNumber === n)) continue
    const prev = byNumber.get(n)
    const size = prev?.size ?? Math.max(0, Math.min(partSize, item.size - (n - 1) * partSize))
    parts.push({
      partNumber: n,
      url: prev?.url ?? '',
      size,
      loaded: size,
      etag: prev?.etag ?? 'received',
      attempts: prev?.attempts ?? 0,
    })
  }
  for (const prev of item.parts) {
    if (!parts.some((p) => p.partNumber === prev.partNumber) && prev.etag !== null) parts.push(prev)
  }
  parts.sort((a, b) => a.partNumber - b.partNumber)
  return { ...item, needsRefresh: false, expiresAt: status.expires_at, partSize, parts }
}

function update(
  state: UploadState,
  clientId: string,
  fn: (item: UploadItemState) => UploadItemState,
): UploadState {
  const item = state.items[clientId]
  if (!item) return state
  const next = fn(item)
  if (next === item) return state
  return { ...state, items: { ...state.items, [clientId]: next } }
}

function finalize(prev: UploadState, next: UploadState): UploadState {
  const queue = deriveQueue(next)
  if (queue === next.queue && next === prev) return prev
  let finishedAt = next.finishedAt
  if (queue === 'done' && prev.queue !== 'done') finishedAt = Date.now()
  if (queue !== 'done') finishedAt = null
  return { ...next, queue, finishedAt }
}

export function reduce(state: UploadState, action: Action): UploadState {
  return finalize(state, step(state, action))
}

function step(state: UploadState, action: Action): UploadState {
  switch (action.type) {
    case 'add': {
      const items = { ...state.items }
      const order = state.order.slice()
      for (const meta of action.files) {
        if (items[meta.clientId]) continue
        items[meta.clientId] = newItem(meta)
        order.push(meta.clientId)
      }
      return { ...state, items, order, finishedAt: null }
    }
    case 'restore': {
      const items = { ...state.items }
      const order = state.order.slice()
      for (const restored of action.items) {
        if (items[restored.clientId]) continue
        const status: ItemStatus = restored.mediaId ? 'uploading' : 'waiting-intent'
        items[restored.clientId] = {
          ...restored,
          status,
          intentRequested: false,
          needsRefresh: restored.mediaId !== null,
          restored: true,
          error: null,
          preview: restored.preview?.kind === 'icon' ? restored.preview : null,
        }
        order.push(restored.clientId)
      }
      return { ...state, items, order, finishedAt: null }
    }
    case 'preview-start':
      return update(state, action.clientId, (item) =>
        item.status === 'picked' ? { ...item, status: 'previewing' } : item,
      )
    case 'preview-ready':
      return update(state, action.clientId, (item) => ({
        ...item,
        preview: action.preview,
        status:
          item.status === 'previewing' || item.status === 'picked' ? 'waiting-intent' : item.status,
      }))
    case 'intent-requested': {
      let next = state
      for (const id of action.clientIds) {
        next = update(next, id, (item) =>
          item.status === 'waiting-intent' ? { ...item, intentRequested: true } : item,
        )
      }
      return next
    }
    case 'intent-received':
      return update(state, action.clientId, (item) => {
        if (item.status !== 'waiting-intent' && item.status !== 'paused') return item
        const init = action.init
        if (init.mode === 'duplicate') {
          return {
            ...item,
            intentRequested: false,
            mediaId: init.media_id,
            mode: 'duplicate',
            duplicateOf: init.duplicate_of ?? null,
            status: 'done',
            parts: [],
          }
        }
        const { parts, partSize } = partsFromInit(init, item.size)
        return {
          ...item,
          intentRequested: false,
          mediaId: init.media_id,
          mode: init.mode,
          headers: init.headers ?? {},
          parts,
          partSize,
          expiresAt: init.expires_at,
          needsRefresh: false,
          status: state.online ? 'uploading' : 'paused',
        }
      })
    case 'intent-failed': {
      let next = state
      for (const id of action.clientIds) {
        next = update(next, id, (item) => {
          if (item.status !== 'waiting-intent') return item
          if (action.retryable) return { ...item, intentRequested: false }
          return { ...item, intentRequested: false, status: 'failed', error: action.code }
        })
      }
      return next
    }
    case 'part-progress':
      return update(state, action.clientId, (item) => {
        if (item.status !== 'uploading') return item
        return {
          ...item,
          parts: item.parts.map((p) =>
            p.partNumber === action.partNumber && p.etag === null
              ? { ...p, loaded: Math.min(p.size, action.loaded) }
              : p,
          ),
        }
      })
    case 'part-done':
      return update(state, action.clientId, (item) => ({
        ...item,
        parts: item.parts.map((p) =>
          p.partNumber === action.partNumber
            ? { ...p, loaded: p.size, etag: action.etag ?? '' }
            : p,
        ),
      }))
    case 'part-failed':
      return update(state, action.clientId, (item) => {
        if (item.status !== 'uploading' && item.status !== 'paused') return item
        const part = item.parts.find((p) => p.partNumber === action.partNumber)
        if (!part) return item
        const attempts = part.attempts + 1
        const parts = item.parts.map((p) =>
          p.partNumber === action.partNumber ? { ...p, loaded: 0, attempts } : p,
        )
        if (!state.online) return { ...item, parts, status: 'paused' }
        if (attempts >= MAX_PART_ATTEMPTS) {
          return {
            ...item,
            parts,
            status: 'failed',
            error: action.httpStatus === 403 ? 'forbidden' : 'network',
          }
        }
        return { ...item, parts, needsRefresh: item.needsRefresh || action.httpStatus === 403 }
      })
    case 'urls-refreshed':
      return update(state, action.clientId, (item) => mergeStatus(item, action.status))
    case 'refresh-failed':
      return update(state, action.clientId, (item) =>
        item.status === 'uploading' ? { ...item, status: 'failed', error: action.code } : item,
      )
    case 'completing':
      return update(state, action.clientId, (item) =>
        item.status === 'uploading' ? { ...item, status: 'completing' } : item,
      )
    case 'completed':
      return update(state, action.clientId, (item) => ({
        ...item,
        status: 'done',
        result: action.item,
        error: null,
      }))
    case 'failed':
      return update(state, action.clientId, (item) =>
        isTerminal(item.status) ? item : { ...item, status: 'failed', error: action.code },
      )
    case 'retry':
      return update(state, action.clientId, (item) => {
        if (item.status !== 'failed') return item
        const base = { ...item, error: null, intentRequested: false }
        if (!item.mediaId || item.mode === null) return { ...base, status: 'waiting-intent' }
        return {
          ...base,
          status: state.online ? 'uploading' : 'paused',
          needsRefresh: true,
          parts: item.parts.map((p) => ({
            ...p,
            attempts: 0,
            loaded: p.etag !== null ? p.size : 0,
          })),
        }
      })
    case 'cancel':
      return update(state, action.clientId, (item) =>
        isTerminal(item.status) ? item : { ...item, status: 'cancelled' },
      )
    case 'remove': {
      if (!state.items[action.clientId]) return state
      const items = { ...state.items }
      delete items[action.clientId]
      return { ...state, items, order: state.order.filter((id) => id !== action.clientId) }
    }
    case 'offline': {
      const items: Record<string, UploadItemState> = {}
      for (const [id, item] of Object.entries(state.items)) {
        items[id] =
          item.status === 'uploading'
            ? {
                ...item,
                status: 'paused',
                parts: item.parts.map((p) => (p.etag === null ? { ...p, loaded: 0 } : p)),
              }
            : item.status === 'waiting-intent'
              ? { ...item, intentRequested: false }
              : item
      }
      return { ...state, online: false, items }
    }
    case 'online': {
      const items: Record<string, UploadItemState> = {}
      for (const [id, item] of Object.entries(state.items)) {
        items[id] =
          item.status === 'paused'
            ? {
                ...item,
                status: item.mediaId ? 'uploading' : 'waiting-intent',
                needsRefresh: item.mediaId !== null,
              }
            : item
      }
      return { ...state, online: true, items }
    }
    case 'acknowledge-finished':
      return { ...state, finishedAt: null }
  }
}

// Selectors

export function itemsOf(state: UploadState): UploadItemState[] {
  return state.order.map((id) => state.items[id]).filter((i): i is UploadItemState => !!i)
}

export function bytesSent(item: UploadItemState): number {
  if (item.status === 'done' || item.status === 'completing') return item.size
  return item.parts.reduce((sum, p) => sum + (p.etag !== null ? p.size : p.loaded), 0)
}

export function percentOf(item: UploadItemState): number {
  if (item.size === 0) return 100
  return Math.min(100, Math.floor((bytesSent(item) / item.size) * 100))
}

export function allPartsDone(item: UploadItemState): boolean {
  return item.parts.length > 0 && item.parts.every((p) => p.etag !== null)
}

export function counts(state: UploadState): {
  done: number
  failed: number
  total: number
  succeeded: number
} {
  const items = itemsOf(state)
  const done = items.filter((i) => i.status === 'done').length
  const failed = items.filter((i) => i.status === 'failed').length
  const succeeded = items.filter((i) => i.status === 'done' && i.mode !== 'duplicate').length
  return { done, failed, total: items.filter((i) => i.status !== 'cancelled').length, succeeded }
}

export function isExpired(item: UploadItemState, now: number = Date.now()): boolean {
  if (!item.expiresAt) return false
  const at = Date.parse(item.expiresAt)
  return Number.isFinite(at) && at - 5_000 <= now
}

export function mapErrorCode(status: number, code?: string | null): ErrorCode {
  if (code === 'too_large' || status === 413) return 'too_large'
  if (code === 'unsupported_media' || status === 415) return 'unsupported_media'
  if (code === 'forbidden' || status === 403) return 'forbidden'
  if (code === 'conflict' || status === 409) return 'conflict'
  if (status === 0 || status >= 500) return 'network'
  return 'unknown'
}
