import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import type { GridItem } from '~/lib/api/types'
import { insertGridItem } from '~/lib/live/applyLiveEvent'
import { ensureGuest } from '~/lib/queries/event'
import { keys } from '~/lib/queries/keys'
import {
  abortUpload,
  completeUpload,
  createUploadIntents,
  getUploadStatus,
} from '~/lib/queries/uploads'
import { idbManifest, noopManifest, supportsManifest } from './manifest'
import { subscribeOnline } from './online'
import { UploadQueue } from './queue'
import type { UploadState } from './types'

const queues = new Map<string, UploadQueue>()

function queueFor(slug: string, onDone: (item: GridItem) => void) {
  let queue = queues.get(slug)
  if (!queue) {
    queue = new UploadQueue({
      slug,
      api: {
        createIntents: (files) => createUploadIntents(slug, files),
        getStatus: getUploadStatus,
        complete: completeUpload,
        abort: abortUpload,
      },
      ensureGuest: () => ensureGuest(slug),
      manifest: supportsManifest() ? idbManifest : noopManifest,
      onDone,
    })
    queues.set(slug, queue)
  }
  return queue
}

/**
 * Binds the per-event upload queue (kept alive across client navigations) to React.
 * `anonymous` makes the queue call POST /events/{slug}/guests once before the first intent.
 */
export function useUploader(slug: string, anonymous: boolean) {
  const queryClient = useQueryClient()
  const [queue] = useState(() =>
    queueFor(slug, (item) => {
      insertGridItem(queryClient, slug, item)
      queryClient.invalidateQueries({ queryKey: keys.event(slug) })
    }),
  )
  const [resumable, setResumable] = useState(0)

  useEffect(() => {
    queue.setNeedsGuest(anonymous)
  }, [queue, anonymous])

  const state = useSyncExternalStore<UploadState>(
    (cb) => queue.subscribe(cb),
    () => queue.getState(),
    () => queue.getState(),
  )

  useEffect(() => subscribeOnline((online) => queue.setOnline(online)), [queue])

  useEffect(() => {
    let active = true
    queue.resumable().then((n) => {
      if (active) setResumable(n)
    })
    return () => {
      active = false
    }
  }, [queue])

  useEffect(() => {
    const running =
      state.queue === 'running' || state.queue === 'draining' || state.queue === 'paused-offline'
    if (!running) return
    const handler = (ev: BeforeUnloadEvent) => {
      ev.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [state.queue])

  const addFiles = useCallback((files: File[]) => queue.addFiles(files), [queue])
  const retry = useCallback((id: string) => queue.retry(id), [queue])
  const cancel = useCallback((id: string) => queue.cancel(id), [queue])
  const resume = useCallback(async () => {
    await queue.resume()
    setResumable(0)
  }, [queue])
  const discardResumable = useCallback(async () => {
    await queue.discardResumable()
    setResumable(0)
  }, [queue])
  const acknowledgeFinished = useCallback(() => queue.acknowledgeFinished(), [queue])

  return {
    state,
    addFiles,
    retry,
    cancel,
    resumable,
    resume,
    discardResumable,
    acknowledgeFinished,
  }
}
