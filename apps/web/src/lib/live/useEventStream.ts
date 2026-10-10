import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { keys } from '~/lib/queries/keys'
import { applyLiveEvent, liveEventNames, parseLiveEvent } from './applyLiveEvent'

const POLL_INTERVAL = 10_000
const STREAM_RETRY = 60_000
const ERROR_WINDOW = 30_000

/**
 * One EventSource per event layout. Patches the Query cache on media and like events.
 * After two errors within 30 s the media lists poll every 10 s and the stream is retried every 60 s.
 * Paused while the document is hidden.
 */
export function useEventStream(slug: string, enabled = true) {
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!enabled || typeof window === 'undefined' || typeof EventSource === 'undefined') return

    let source: EventSource | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let errors: number[] = []
    let polling = false
    let disposed = false

    const url = `/api/v1/events/${encodeURIComponent(slug)}/events`

    const startPolling = () => {
      if (polling) return
      polling = true
      queryClient.setQueryDefaults(keys.mediaAll(slug), { refetchInterval: POLL_INTERVAL })
      queryClient.invalidateQueries({ queryKey: keys.mediaAll(slug) })
    }
    const stopPolling = () => {
      if (!polling) return
      polling = false
      queryClient.setQueryDefaults(keys.mediaAll(slug), { refetchInterval: false })
    }

    const close = () => {
      source?.close()
      source = null
    }

    const open = () => {
      if (disposed || source || document.hidden) return
      source = new EventSource(url, { withCredentials: true })
      source.onopen = () => {
        errors = []
        if (polling) {
          stopPolling()
          queryClient.invalidateQueries({ queryKey: keys.mediaAll(slug) })
        }
      }
      source.onerror = () => {
        const now = Date.now()
        errors = errors.filter((t) => now - t < ERROR_WINDOW)
        errors.push(now)
        if (errors.length >= 2) {
          close()
          startPolling()
          if (retryTimer) clearTimeout(retryTimer)
          retryTimer = setTimeout(() => {
            retryTimer = null
            open()
          }, STREAM_RETRY)
        }
      }
      for (const name of liveEventNames) {
        source.addEventListener(name, (ev) => {
          const event = parseLiveEvent(name, (ev as MessageEvent<string>).data)
          if (event) applyLiveEvent(queryClient, slug, event)
        })
      }
    }

    const onVisibility = () => {
      if (document.hidden) {
        close()
        if (retryTimer) {
          clearTimeout(retryTimer)
          retryTimer = null
        }
      } else {
        queryClient.invalidateQueries({ queryKey: keys.mediaAll(slug) })
        open()
      }
    }

    document.addEventListener('visibilitychange', onVisibility)
    open()

    return () => {
      disposed = true
      document.removeEventListener('visibilitychange', onVisibility)
      if (retryTimer) clearTimeout(retryTimer)
      close()
      stopPolling()
    }
  }, [slug, enabled, queryClient])
}
