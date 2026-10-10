import type { QueryClient } from '@tanstack/react-query'
import { notFound, redirect } from '@tanstack/react-router'
import { isApiError } from '~/lib/api/client'
import type { Event, Me } from '~/lib/api/types'
import { eventQuery, isHost } from '~/lib/queries/event'
import { meQuery } from '~/lib/queries/me'

export async function requireSession(queryClient: QueryClient, next: string): Promise<Me> {
  let me: Me
  try {
    me = await queryClient.ensureQueryData(meQuery())
  } catch {
    me = { authenticated: false, locale: 'de' }
  }
  if (!me.authenticated) {
    throw redirect({ to: '/login', search: { next } })
  }
  return me
}

export async function loadEvent(queryClient: QueryClient, slug: string): Promise<Event> {
  try {
    return await queryClient.ensureQueryData(eventQuery(slug))
  } catch (error) {
    if (isApiError(error) && error.status === 404) throw notFound()
    throw error
  }
}

export async function requireHost(
  queryClient: QueryClient,
  slug: string,
  next: string,
): Promise<Event> {
  const event = await loadEvent(queryClient, slug)
  if (isHost(event)) return event
  await requireSession(queryClient, next)
  throw redirect({ to: '/e/$slug', params: { slug } })
}

/** Only same-origin paths are allowed as `next` targets. */
export function safeNext(value: string | undefined, fallback = '/'): string {
  if (!value?.startsWith('/') || value.startsWith('//')) return fallback
  return value
}
