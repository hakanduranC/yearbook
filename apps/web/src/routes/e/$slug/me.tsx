import { createFileRoute, redirect } from '@tanstack/react-router'

/** "Photos of me" lives in the gallery under the `me` filter; this path stays for old links. */
export const Route = createFileRoute('/e/$slug/me')({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: '/e/$slug/photos',
      params: { slug: params.slug },
      search: { filter: 'me' },
    })
  },
})
