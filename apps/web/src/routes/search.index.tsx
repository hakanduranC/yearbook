import { createFileRoute, Link } from '@tanstack/react-router'
import * as v from 'valibot'
import { AgentPanel } from '~/components/AgentPanel'
import { PageHeader } from '~/components/PageHeader'
import { useT } from '~/i18n'
import { requireSession } from '~/lib/guards'

export const Route = createFileRoute('/search/')({
  validateSearch: v.object({ q: v.optional(v.string()), command: v.optional(v.string()) }),
  beforeLoad: async ({ context: { queryClient }, location }) => {
    await requireSession(queryClient, location.href)
  },
  component: MemberSearch,
})

function MemberSearch() {
  const t = useT()
  const { q, command } = Route.useSearch()
  return (
    <>
      <PageHeader
        title={t('search.title')}
        back="/"
        right={
          <Link
            to="/search/saved"
            style={{
              minHeight: 44,
              display: 'inline-flex',
              alignItems: 'center',
              padding: '0 8px',
            }}
          >
            {t('search.savedTitle')}
          </Link>
        }
      />
      <main data-search-page>
        <AgentPanel
          key={`${q ?? ''}|${command ?? ''}`}
          slug={null}
          initialQuery={q}
          initialCommand={command}
        />
      </main>
    </>
  )
}
