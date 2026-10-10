import { queryOptions } from '@tanstack/react-query'
import { api, ok, okVoid } from '~/lib/api/client'
import type { Me, MeUpdate } from '~/lib/api/types'
import { keys } from './keys'

export function meQuery() {
  return queryOptions({
    queryKey: keys.me(),
    queryFn: async (): Promise<Me> => ok(await api.GET('/me')),
    staleTime: 60_000,
  })
}

export async function updateMe(body: MeUpdate): Promise<Me> {
  return ok(await api.PATCH('/me', { body }))
}

export async function requestMagicLink(body: {
  email: string
  locale?: 'de' | 'en' | 'tr'
  next?: string
}) {
  return ok(await api.POST('/auth/magic', { body }))
}

export async function verifyMagicLink(token: string) {
  return ok(await api.POST('/auth/verify', { body: { token } }))
}

export async function logout() {
  return ok(await api.POST('/auth/logout'))
}

export async function deleteMyFaceData(): Promise<void> {
  okVoid(await api.DELETE('/me/face-data'))
}
