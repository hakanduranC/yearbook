import type { Preview } from './types'

export function mediaKind(type: string, name: string): 'photo' | 'video' {
  if (type.startsWith('video/')) return 'video'
  if (/\.(mp4|mov|m4v|webm)$/i.test(name)) return 'video'
  return 'photo'
}

/**
 * A 160 px wide preview via createImageBitmap. HEIC on browsers that cannot decode it,
 * and videos, fall back to a file icon.
 */
export async function makePreview(file: Blob, type: string, name: string): Promise<Preview> {
  const media = mediaKind(type, name)
  if (media === 'video' || typeof createImageBitmap !== 'function') return { kind: 'icon', media }
  try {
    const bitmap = await createImageBitmap(file, { resizeWidth: 160, resizeQuality: 'low' })
    try {
      const blob = await bitmapToBlob(bitmap)
      if (!blob) return { kind: 'icon', media }
      return { kind: 'image', url: URL.createObjectURL(blob) }
    } finally {
      bitmap.close()
    }
  } catch {
    return { kind: 'icon', media }
  }
}

async function bitmapToBlob(bitmap: ImageBitmap): Promise<Blob | null> {
  if (typeof OffscreenCanvas !== 'undefined') {
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height)
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(bitmap, 0, 0)
    return canvas.convertToBlob({ type: 'image/jpeg', quality: 0.75 })
  }
  const canvas = document.createElement('canvas')
  canvas.width = bitmap.width
  canvas.height = bitmap.height
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  ctx.drawImage(bitmap, 0, 0)
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.75))
}

export function revokePreview(preview: Preview | null) {
  if (preview?.kind === 'image') URL.revokeObjectURL(preview.url)
}
