# Yearbook web

TanStack Start app for hosts and guests: event landing with OG tags, resumable guest uploads, the virtualized gallery with lightbox, likes, select and zip, and live updates over SSE. German by default, English by `Accept-Language` or the `yb_lang` cookie.

## Run

```sh
pnpm install                      # at the repo root
pnpm --filter @yearbook/openapi generate
cd apps/web
pnpm dev                          # http://localhost:3000, proxies /api/v1 to http://localhost:8080
```

Environment (from the repo `.env`): `API_INTERNAL_URL` (server-side base URL for SSR, default `http://localhost:8080/api/v1`), `PUBLIC_WEB_ORIGIN` (absolute URLs in OG tags and QR links), `API_PROXY_TARGET` (dev proxy target, default `http://localhost:8080`).

## Check and test

```sh
pnpm check        # tsc + biome
pnpm test         # vitest: upload machine, queue driver, grouping, i18n, live cache patching
pnpm test:e2e     # playwright against tests/e2e/mock-api.mjs; E2E_LIVE=1 uses the real API on :8080
```

Playwright projects: `iphone-14` (WebKit), `pixel-7` (Chromium) and `iphone-14-chromium` for hosts where WebKit cannot run. Fixture JPEGs are rendered into `tests/e2e/fixtures` by the global setup.

## Layout

```
src/router.tsx, src/start.ts      framework touchpoints (QueryClient per request, SSR query integration)
src/routes                        file-based routes; e/$slug/* is the event area, api/health.ts a server route
src/components/<Name>             one folder per component, CSS Modules on tokens.css
src/lib/api                       openapi-fetch client typed from @yearbook/openapi, SSR cookie forwarding
src/lib/queries                   queryOptions factories; keys ['event', slug, 'media', filter]
src/lib/upload                    pure reducer (machine.ts), queue driver, XHR transport, IndexedDB manifest
src/lib/live                      EventSource hook and cache patching for media.ready / removed / like.changed
src/i18n                          de.ts is the source; en.ts must satisfy the same shape
src/styles                        tokens, reset, self-hosted fonts, global
```

## Build

`pnpm build` produces `.output/` through Nitro; `node .output/server/index.mjs` serves it. `apps/web/Dockerfile` builds from the repo root.
