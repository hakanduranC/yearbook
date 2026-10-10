import type { GridItem, UploadInit, UploadStatus } from '~/lib/api/types'

export type ItemStatus =
  | 'picked'
  | 'previewing'
  | 'waiting-intent'
  | 'uploading'
  | 'completing'
  | 'done'
  | 'failed'
  | 'paused'
  | 'cancelled'

export type QueueStatus = 'idle' | 'running' | 'paused-offline' | 'draining' | 'done'

export type ErrorCode =
  | 'too_large'
  | 'unsupported_media'
  | 'forbidden'
  | 'network'
  | 'conflict'
  | 'unknown'

export type Preview = { kind: 'image'; url: string } | { kind: 'icon'; media: 'photo' | 'video' }

export interface FileMeta {
  clientId: string
  name: string
  size: number
  type: string
  lastModified: number
}

export interface PartState {
  partNumber: number
  url: string
  /** Bytes in this part. */
  size: number
  /** Bytes confirmed or in flight for this part. */
  loaded: number
  etag: string | null
  attempts: number
}

export interface UploadItemState extends FileMeta {
  status: ItemStatus
  preview: Preview | null
  mediaId: string | null
  mode: 'single' | 'multipart' | 'duplicate' | null
  headers: Record<string, string>
  parts: PartState[]
  partSize: number
  expiresAt: string | null
  duplicateOf: string | null
  /** An intent request is in flight for this item. */
  intentRequested: boolean
  /** Presigned URLs were rejected; fetch fresh ones before the next PUT. */
  needsRefresh: boolean
  error: ErrorCode | null
  result: GridItem | null
  restored: boolean
}

export interface UploadState {
  items: Record<string, UploadItemState>
  order: string[]
  online: boolean
  queue: QueueStatus
  /** Set once when the queue transitions to `done`; cleared when new files are added. */
  finishedAt: number | null
}

export type Action =
  | { type: 'add'; files: FileMeta[] }
  | { type: 'restore'; items: UploadItemState[] }
  | { type: 'preview-start'; clientId: string }
  | { type: 'preview-ready'; clientId: string; preview: Preview }
  | { type: 'intent-requested'; clientIds: string[] }
  | { type: 'intent-received'; clientId: string; init: UploadInit }
  | { type: 'intent-failed'; clientIds: string[]; code: ErrorCode; retryable: boolean }
  | { type: 'part-progress'; clientId: string; partNumber: number; loaded: number }
  | { type: 'part-done'; clientId: string; partNumber: number; etag: string | null }
  | { type: 'part-failed'; clientId: string; partNumber: number; httpStatus: number }
  | { type: 'urls-refreshed'; clientId: string; status: UploadStatus }
  | { type: 'refresh-failed'; clientId: string; code: ErrorCode }
  | { type: 'completing'; clientId: string }
  | { type: 'completed'; clientId: string; item: GridItem }
  | { type: 'failed'; clientId: string; code: ErrorCode }
  | { type: 'retry'; clientId: string }
  | { type: 'cancel'; clientId: string }
  | { type: 'remove'; clientId: string }
  | { type: 'offline' }
  | { type: 'online' }
  | { type: 'acknowledge-finished' }

export const MAX_PART_ATTEMPTS = 6
export const MAX_CONCURRENT = 3
export const INTENT_BATCH = 20
export const INTENT_DEBOUNCE_MS = 150
export const MANIFEST_BLOB_BUDGET = 500 * 1024 * 1024
