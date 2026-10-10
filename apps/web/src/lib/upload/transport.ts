export class TransportError extends Error {
  readonly status: number
  constructor(status: number, message = `PUT failed with ${status}`) {
    super(message)
    this.name = 'TransportError'
    this.status = status
  }
}

export interface PutHandle {
  promise: Promise<{ etag: string | null }>
  abort: () => void
}

/** PUT a blob to a presigned URL with upload progress. Network errors surface as status 0. */
export function putBlob(
  url: string,
  blob: Blob,
  headers: Record<string, string>,
  onProgress: (loaded: number) => void,
): PutHandle {
  const xhr = new XMLHttpRequest()
  const promise = new Promise<{ etag: string | null }>((resolve, reject) => {
    xhr.open('PUT', url, true)
    for (const [name, value] of Object.entries(headers)) {
      if (name.toLowerCase() === 'content-length') continue
      try {
        xhr.setRequestHeader(name, value)
      } catch {
        // Forbidden header names are set by the browser.
      }
    }
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) onProgress(ev.loaded)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const raw = xhr.getResponseHeader('ETag') ?? xhr.getResponseHeader('etag')
        resolve({ etag: raw ? raw.replace(/^W\//, '').replace(/^"|"$/g, '') : null })
      } else {
        reject(new TransportError(xhr.status))
      }
    }
    xhr.onerror = () => reject(new TransportError(0, 'Network error'))
    xhr.onabort = () => reject(new TransportError(-1, 'Aborted'))
    xhr.ontimeout = () => reject(new TransportError(0, 'Timeout'))
    xhr.send(blob)
  })
  return { promise, abort: () => xhr.abort() }
}
