import { useMutation, useQueryClient } from '@tanstack/react-query'
import { keys } from '~/lib/queries/keys'
import { claimPerson } from '~/lib/queries/people'

/** Invalidates everything a claim changes: the person, the list, event counts, the me filter and the viewer's home. */
export function useClaim(slug: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => claimPerson(id),
    onSuccess: (person) => {
      queryClient.setQueryData(keys.person(person.id), person)
      queryClient.invalidateQueries({ queryKey: keys.people(slug) })
      queryClient.invalidateQueries({ queryKey: keys.event(slug), exact: true })
      queryClient.invalidateQueries({ queryKey: keys.mediaAll(slug) })
      queryClient.invalidateQueries({ queryKey: keys.me() })
      queryClient.invalidateQueries({ queryKey: keys.years() })
      queryClient.invalidateQueries({ queryKey: keys.suggestions() })
    },
  })
}
