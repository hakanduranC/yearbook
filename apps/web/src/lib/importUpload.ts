import type { CompletedPart, UploadInit } from '~/lib/api/types'
import { putBlob } from '~/lib/upload/transport'

/**
 * Uploads an archive to the presigned target of an ImportInit. Single PUT or sequential parts;
 * returns the completed parts for multipart so the caller can POST /imports/{id}/complete.
 */
export async function uploadArchive(
  file: Blob,
  init: UploadInit,
  onProgress: (loaded: number, total: number) => void,
  put: typeof putBlob = putBlob,
): Promise<CompletedPart[] | undefined> {
  const total = file.size
  if (init.mode === 'duplicate') {
    onProgress(total, total)
    return undefined
  }
  if (init.mode === 'single') {
    if (!init.url) throw new Error('missing upload url')
    await put(init.url, file, init.headers ?? {}, (loaded) => onProgress(loaded, total)).promise
    onProgress(total, total)
    return undefined
  }
  const parts = [...(init.parts ?? [])].sort((a, b) => a.part_number - b.part_number)
  const size = init.part_size ?? Math.ceil(total / Math.max(1, parts.length))
  const done: CompletedPart[] = []
  let base = 0
  for (const part of parts) {
    const start = (part.part_number - 1) * size
    const end = Math.min(total, start + size)
    if (start >= total) break
    const chunk = file.slice(start, end)
    const { etag } = await put(part.url, chunk, init.headers ?? {}, (loaded) =>
      onProgress(base + loaded, total),
    ).promise
    base += chunk.size
    done.push({ part_number: part.part_number, etag: etag ?? '' })
    onProgress(base, total)
  }
  return done
}
