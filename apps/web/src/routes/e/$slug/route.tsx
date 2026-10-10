import { createFileRoute, Outlet } from '@tanstack/react-router'
import { BottomBarProvider } from '~/components/BottomBar'
import { loadEvent } from '~/lib/guards'
import { useEventStream } from '~/lib/live/useEventStream'

export const Route = createFileRoute('/e/$slug')({
  loader: async ({ context: { queryClient }, params }) => {
    await loadEvent(queryClient, params.slug)
  },
  component: EventLayout,
})

function EventLayout() {
  const { slug } = Route.useParams()
  // Client only: EventSource does not exist on the server.
  useEventStream(slug)
  return (
    <BottomBarProvider>
      <Outlet />
    </BottomBarProvider>
  )
}
