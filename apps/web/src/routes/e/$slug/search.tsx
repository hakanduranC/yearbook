import { useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import * as v from 'valibot'
import { AgentPanel } from '~/components/AgentPanel'
import { PageHeader } from '~/components/PageHeader'
import { useT } from '~/i18n'
import { eventQuery } from '~/lib/queries/event'

export const Route = createFileRoute('/e/$slug/search')({
  validateSearch: v.object({ q: v.optional(v.string()), command: v.optional(v.string()) }),
  component: EventSearch,
})

function EventSearch() {
  const t = useT()
  const { slug } = Route.useParams()
  const { q, command } = Route.useSearch()
  const { data: event } = useSuspenseQuery(eventQuery(slug))
  return (
    <>
      <PageHeader title={t('search.title')} back="/e/$slug/photos" backParams={{ slug }} />
      <main data-search-page>
        <AgentPanel
          key={`${q ?? ''}|${command ?? ''}`}
          slug={slug}
          eventTitle={event.title}
          initialQuery={q}
          initialCommand={command}
        />
      </main>
    </>
  )
}
