import { queryOptions } from '@tanstack/react-query'
import { api, ok, okVoid } from '~/lib/api/client'
import type { Face, PeopleList, Person, PersonUpdate, Suggestion } from '~/lib/api/types'
import { keys } from './keys'

export function peopleQuery(slug: string) {
  return queryOptions({
    queryKey: keys.people(slug),
    queryFn: async (): Promise<PeopleList> =>
      ok(await api.GET('/events/{slug}/people', { params: { path: { slug } } })),
  })
}

export function personQuery(id: string) {
  return queryOptions({
    queryKey: keys.person(id),
    queryFn: async (): Promise<Person> =>
      ok(await api.GET('/people/{person_id}', { params: { path: { person_id: id } } })),
  })
}

export function mediaFacesQuery(mediaId: string) {
  return queryOptions({
    queryKey: keys.mediaFaces(mediaId),
    queryFn: async (): Promise<Face[]> =>
      ok(await api.GET('/media/{media_id}/faces', { params: { path: { media_id: mediaId } } }))
        .faces,
  })
}

export function myPeopleQuery() {
  return queryOptions({
    queryKey: keys.myPeople(),
    queryFn: async (): Promise<PeopleList> => ok(await api.GET('/me/people')),
  })
}

export function suggestionsQuery() {
  return queryOptions({
    queryKey: keys.suggestions(),
    queryFn: async (): Promise<Suggestion[]> => ok(await api.GET('/me/suggestions')).suggestions,
  })
}

export async function updatePerson(id: string, body: PersonUpdate): Promise<Person> {
  return ok(await api.PATCH('/people/{person_id}', { params: { path: { person_id: id } }, body }))
}

export async function claimPerson(id: string): Promise<Person> {
  return ok(await api.POST('/people/{person_id}/claim', { params: { path: { person_id: id } } }))
}

export async function unclaimPerson(id: string): Promise<Person> {
  return ok(await api.DELETE('/people/{person_id}/claim', { params: { path: { person_id: id } } }))
}

export async function mergePeople(person_ids: string[]): Promise<Person> {
  return ok(await api.POST('/people/merge', { body: { person_ids } }))
}

export async function splitPerson(id: string, face_ids: string[]): Promise<Person> {
  return ok(
    await api.POST('/people/{person_id}/split', {
      params: { path: { person_id: id } },
      body: { face_ids },
    }),
  )
}

export async function faceNotPerson(faceId: string): Promise<void> {
  okVoid(await api.POST('/faces/{face_id}/not-person', { params: { path: { face_id: faceId } } }))
}

export function faceCropUrl(faceId: string): string {
  return `/api/v1/faces/${encodeURIComponent(faceId)}/crop.jpg`
}

/** Faces of a person for the manage strip: the contract has no per-person face list, so we page the person's media and read /media/{id}/faces. */
export async function listPersonFaces(slug: string, personId: string, limit = 24): Promise<Face[]> {
  const page = ok(
    await api.GET('/events/{slug}/media', {
      params: { path: { slug }, query: { filter: `person:${personId}`, limit } },
    }),
  )
  const all = await Promise.all(
    page.items.map(async (item) => {
      try {
        return ok(
          await api.GET('/media/{media_id}/faces', { params: { path: { media_id: item.id } } }),
        ).faces
      } catch {
        return []
      }
    }),
  )
  return all.flat().filter((f) => f.person_id === personId)
}
