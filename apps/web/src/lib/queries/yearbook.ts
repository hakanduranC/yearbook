import { queryOptions } from '@tanstack/react-query'
import { api, ok } from '~/lib/api/client'
import type { YearRecap, YearSummary } from '~/lib/api/types'
import { keys } from './keys'

export function yearsQuery() {
  return queryOptions({
    queryKey: keys.years(),
    queryFn: async (): Promise<YearSummary[]> => ok(await api.GET('/me/years')).years,
  })
}

export function yearQuery(year: number) {
  return queryOptions({
    queryKey: keys.year(year),
    queryFn: async (): Promise<YearRecap> =>
      ok(await api.GET('/me/years/{year}', { params: { path: { year } } })),
  })
}
