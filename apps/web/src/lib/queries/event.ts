import { queryOptions } from '@tanstack/react-query'
import { api, ok, okVoid } from '~/lib/api/client'
import type { Event, EventCreate, EventStatus, EventUpdate, Guest } from '~/lib/api/types'
import { keys } from './keys'

export function eventsQuery() {
  return queryOptions({
    queryKey: keys.events(),
    queryFn: async () => ok(await api.GET('/events')),
  })
}

export function eventQuery(slug: string) {
  return queryOptions({
    queryKey: keys.event(slug),
    queryFn: async (): Promise<Event> =>
      ok(await api.GET('/events/{slug}', { params: { path: { slug } } })),
  })
}

export function eventStatusQuery(slug: string) {
  return queryOptions({
    queryKey: keys.status(slug),
    queryFn: async (): Promise<EventStatus> =>
      ok(await api.GET('/events/{slug}/status', { params: { path: { slug } } })),
  })
}

export async function createEvent(body: EventCreate): Promise<Event> {
  return ok(await api.POST('/events', { body }))
}

export async function updateEvent(slug: string, body: EventUpdate): Promise<Event> {
  return ok(await api.PATCH('/events/{slug}', { params: { path: { slug } }, body }))
}

export async function deleteEvent(slug: string): Promise<void> {
  okVoid(await api.DELETE('/events/{slug}', { params: { path: { slug } } }))
}

export async function ensureGuest(slug: string): Promise<Guest> {
  return ok(await api.POST('/events/{slug}/guests', { params: { path: { slug } } }))
}

export async function updateGuest(slug: string, display_name: string): Promise<Guest> {
  return ok(
    await api.PATCH('/events/{slug}/guests/me', {
      params: { path: { slug } },
      body: { display_name },
    }),
  )
}

export function isHost(event: Event | undefined): boolean {
  return event?.viewer.role === 'host' || event?.viewer.role === 'owner'
}
