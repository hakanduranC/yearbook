import { createFileRoute } from '@tanstack/react-router'
import { EmptyState } from '~/components/EmptyState'

export const Route = createFileRoute('/s/$shareId')({
  component: () => (
    <main className="page page--narrow">
      <EmptyState kind="share" />
    </main>
  ),
})
