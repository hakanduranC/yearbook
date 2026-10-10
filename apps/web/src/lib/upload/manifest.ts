import { type DBSchema, type IDBPDatabase, openDB } from 'idb'
import { MANIFEST_BLOB_BUDGET, type UploadItemState } from './types'

export interface ManifestRecord {
  clientId: string
  slug: string
  name: string
  size: number
  type: string
  lastModified: number
  mediaId: string | null
  mode: UploadItemState['mode']
  partSize: number
  expiresAt: string | null
  etags: Array<{ partNumber: number; etag: string }>
  blob: Blob | null
  blobSize: number
  updatedAt: number
}

interface UploadDb extends DBSchema {
  items: {
    key: string
    value: ManifestRecord
    indexes: { slug: string }
  }
}

export interface Manifest {
  save(slug: string, item: UploadItemState, blob: Blob | null): Promise<void>
  remove(clientId: string): Promise<void>
  listOpen(slug: string): Promise<ManifestRecord[]>
  clear(slug: string): Promise<void>
}

let dbPromise: Promise<IDBPDatabase<UploadDb>> | null = null

function db(): Promise<IDBPDatabase<UploadDb>> {
  if (!dbPromise) {
    dbPromise = openDB<UploadDb>('yearbook-uploads', 1, {
      upgrade(database) {
        const store = database.createObjectStore('items', { keyPath: 'clientId' })
        store.createIndex('slug', 'slug')
      },
    })
  }
  return dbPromise
}

export function supportsManifest(): boolean {
  return typeof indexedDB !== 'undefined'
}

/** IndexedDB manifest with blobs up to 500 MB in total so interrupted uploads survive a reload. */
export const idbManifest: Manifest = {
  async save(slug, item, blob) {
    const database = await db()
    const tx = database.transaction('items', 'readwrite')
    const existing = await tx.store.get(item.clientId)
    let blobToStore = existing?.blob ?? null
    if (!blobToStore && blob) {
      let used = 0
      let cursor = await tx.store.openCursor()
      while (cursor) {
        used += cursor.value.blobSize
        cursor = await cursor.continue()
      }
      if (used + blob.size <= MANIFEST_BLOB_BUDGET) blobToStore = blob
    }
    await tx.store.put({
      clientId: item.clientId,
      slug,
      name: item.name,
      size: item.size,
      type: item.type,
      lastModified: item.lastModified,
      mediaId: item.mediaId,
      mode: item.mode,
      partSize: item.partSize,
      expiresAt: item.expiresAt,
      etags: item.parts
        .filter((p) => p.etag !== null)
        .map((p) => ({ partNumber: p.partNumber, etag: p.etag ?? '' })),
      blob: blobToStore,
      blobSize: blobToStore?.size ?? 0,
      updatedAt: Date.now(),
    })
    await tx.done
  },
  async remove(clientId) {
    const database = await db()
    await database.delete('items', clientId)
  },
  async listOpen(slug) {
    const database = await db()
    return database.getAllFromIndex('items', 'slug', slug)
  },
  async clear(slug) {
    const database = await db()
    const tx = database.transaction('items', 'readwrite')
    let cursor = await tx.store.index('slug').openCursor(slug)
    while (cursor) {
      await cursor.delete()
      cursor = await cursor.continue()
    }
    await tx.done
  },
}

export const noopManifest: Manifest = {
  save: async () => {},
  remove: async () => {},
  listOpen: async () => [],
  clear: async () => {},
}

/** Rebuilds an item from a manifest record; parts get fresh URLs from GET /uploads/{id} later. */
export function itemFromRecord(record: ManifestRecord): UploadItemState {
  return {
    clientId: record.clientId,
    name: record.name,
    size: record.size,
    type: record.type,
    lastModified: record.lastModified,
    status: record.mediaId ? 'uploading' : 'waiting-intent',
    preview: null,
    mediaId: record.mediaId,
    mode: record.mode,
    headers: {},
    parts: record.etags.map((e) => ({
      partNumber: e.partNumber,
      url: '',
      size: record.partSize || record.size,
      loaded: record.partSize || record.size,
      etag: e.etag,
      attempts: 0,
    })),
    partSize: record.partSize,
    expiresAt: record.expiresAt,
    duplicateOf: null,
    intentRequested: false,
    needsRefresh: record.mediaId !== null,
    error: null,
    result: null,
    restored: true,
  }
}
