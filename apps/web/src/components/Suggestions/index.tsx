import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { SuggestionCard } from '~/components/SuggestionCard'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import type { Suggestion } from '~/lib/api/types'
import { keys } from '~/lib/queries/keys'
import { claimPerson, suggestionsQuery } from '~/lib/queries/people'
import { useDismissedSuggestions, visibleSuggestions } from '~/lib/suggestions'
import styles from './Suggestions.module.css'

/** "Also you, at <event>?" cards; Confirm claims, Dismiss hides for this session. */
export function Suggestions() {
  const t = useT()
  const toast = useToast()
  const queryClient = useQueryClient()
  const suggestions = useQuery(suggestionsQuery())
  const [dismissed, dismiss] = useDismissedSuggestions()
  const confirm = useMutation({
    mutationFn: (s: Suggestion) => claimPerson(s.person.id),
    onSuccess: (person) => {
      queryClient.setQueryData(keys.person(person.id), person)
      queryClient.invalidateQueries({ queryKey: keys.suggestions() })
      queryClient.invalidateQueries({ queryKey: keys.years() })
      queryClient.invalidateQueries({ queryKey: keys.events() })
      queryClient.invalidateQueries({ queryKey: keys.myPeople() })
      queryClient.invalidateQueries({ queryKey: keys.me() })
      queryClient.invalidateQueries({ queryKey: keys.event(person.event_slug) })
      toast(t('suggest.confirmed'))
    },
    onError: () => toast(t('common.error')),
  })
  const visible = visibleSuggestions(suggestions.data ?? [], dismissed)
  if (visible.length === 0) return null
  return (
    <section className={styles.section} data-suggestions>
      <h2 className="eyebrow">{t('suggest.section')}</h2>
      <ul className={styles.suggestionList}>
        {visible.map((s) => (
          <li key={s.person.id}>
            <SuggestionCard
              suggestion={s}
              busy={confirm.isPending && confirm.variables?.person.id === s.person.id}
              onConfirm={() => confirm.mutate(s)}
              onDismiss={() => dismiss(s.person.id)}
            />
          </li>
        ))}
      </ul>
    </section>
  )
}
