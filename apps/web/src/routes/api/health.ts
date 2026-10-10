import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/api/health')({
  server: {
    handlers: {
      GET: () =>
        Response.json(
          { status: 'ok', version: process.env.WEB_VERSION ?? 'dev' },
          { headers: { 'cache-control': 'no-store' } },
        ),
    },
  },
})
