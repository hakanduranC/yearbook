import { request as httpRequest, type IncomingMessage, type ServerResponse } from 'node:http'
import type { Plugin } from 'vite'

interface Options {
  /** URL prefix to forward, e.g. `/api/v1`. */
  prefix: string
  /** Target origin, e.g. `http://localhost:8080`. */
  target: string
}

/**
 * Dev-only reverse proxy for the API. Nitro's dev middleware runs ahead of Vite's `server.proxy`,
 * so this plugin registers first and streams matching requests itself. The Host header is left
 * untouched (`changeOrigin: false`) so cookies stay same-origin, and Server-Sent Events get
 * `cache-control: no-cache, no-transform` plus `x-accel-buffering: no` regardless of what the API sent.
 */
export function apiProxy({ prefix, target }: Options): Plugin {
  const origin = new URL(target)
  return {
    name: 'yearbook:api-proxy',
    enforce: 'pre',
    configureServer(server) {
      server.middlewares.use((req: IncomingMessage, res: ServerResponse, next: () => void) => {
        if (
          !req.url ||
          !(
            req.url === prefix ||
            req.url.startsWith(`${prefix}/`) ||
            req.url.startsWith(`${prefix}?`)
          )
        ) {
          return next()
        }
        const upstream = httpRequest(
          {
            protocol: origin.protocol,
            hostname: origin.hostname,
            port: origin.port || (origin.protocol === 'https:' ? 443 : 80),
            method: req.method,
            path: req.url,
            headers: req.headers,
          },
          (proxyRes) => {
            const headers = { ...proxyRes.headers }
            const type = String(headers['content-type'] ?? '')
            if (type.includes('text/event-stream')) {
              headers['cache-control'] = 'no-cache, no-transform'
              headers['x-accel-buffering'] = 'no'
              delete headers['content-length']
            }
            res.writeHead(proxyRes.statusCode ?? 502, headers)
            if (type.includes('text/event-stream')) res.flushHeaders()
            proxyRes.pipe(res)
          },
        )
        upstream.on('error', (err) => {
          if (res.headersSent) return res.end()
          res.writeHead(502, { 'content-type': 'application/json' })
          res.end(
            JSON.stringify({
              error: { code: 'internal', message: `API unreachable: ${err.message}` },
            }),
          )
        })
        req.on('aborted', () => upstream.destroy())
        res.on('close', () => upstream.destroy())
        req.pipe(upstream)
      })
    },
  }
}
