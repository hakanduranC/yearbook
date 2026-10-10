import { createFileRoute } from '@tanstack/react-router'
import { EmptyState } from '~/components/EmptyState'
import { PageHeader } from '~/components/PageHeader'
import { useT } from '~/i18n'

export const Route = createFileRoute('/e/$slug/me')({
  component: Page,
})

function Page() {
  const t = useT()
  const { slug } = Route.useParams()
  return (
    <>
      <PageHeader title={t('me.title')} back="/e/$slug" backParams={{ slug }} />
      <main className="page page--narrow">
        <EmptyState kind="coming-soon" />
      </main>
    </>
  )
}
