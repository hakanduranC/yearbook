# Yearbook web

TanStack Start app for hosts, guests and members: event landing with OG tags, resumable guest uploads, the virtualized gallery with lightbox, likes, select, zip and delete, people (faces, "Is this you?", claim, merge and split), the "Ask for anything" agent with saved chips, highlights and shared albums, the member home with fanned stacks of photos of you, the year recap, the owner dashboard, import and library, and live updates over SSE. German by default, English or Turkish by `Accept-Language` or the `yb_lang` cookie.

## Run

```sh
pnpm install                      # at the repo root
pnpm --filter @yearbook/openapi generate
cd apps/web
pnpm dev                          # http://localhost:3000, proxies /api/v1 to http://localhost:8080
```

Environment (from the repo `.env`): `API_INTERNAL_URL` (server-side base URL for SSR, default `http://localhost:8080/api/v1`), `PUBLIC_WEB_ORIGIN` (absolute URLs in OG tags and QR links), `API_PROXY_TARGET` (dev proxy target, default `http://localhost:8080`).

Without the Go API, `node tests/e2e/mock-api.mjs 8089` plus `API_PROXY_TARGET=http://localhost:8089 API_INTERNAL_URL=http://localhost:8089/api/v1 pnpm dev` gives a fully seeded stand-in: two events, people, albums, shares, an agent that answers by keyword, imports and a library. A `yb_session` cookie with any value signs in as the seeded member.

## Check and test

```sh
pnpm check        # tsc + biome
pnpm test         # vitest: upload machine, queue driver, grouping, i18n (de/en/tr), live cache patching, agent result mapping, fan gesture math, suggestion dismissal, home rows
pnpm test:e2e     # playwright against tests/e2e/mock-api.mjs; E2E_LIVE=1 uses the real API on :8080
```

Playwright projects: `iphone-14` (WebKit), `pixel-7` (Chromium) and `iphone-14-chromium` for hosts where WebKit cannot run. Specs: guest upload, landing OG, Turkish, delete (lightbox and selection), people (claim, rename, wrong person, merge and split), search and agent (every result kind, attachments, saved chips, fallback), home and year (fan swipe, suggestions, recap), owner dashboard (events, albums, shared album OG, highlights), import and library. Fixture JPEGs are rendered into `tests/e2e/fixtures` by the global setup.

## Routes

| Area | Routes |
|---|---|
| Public (SSR, OG tags) | `/e/$slug` landing · `/e/$slug/upload` · `/e/$slug/photos` gallery with filters `all`, `best`, `videos`, `mine`, `me`, `person:{id}` and saved chips · `/e/$slug/photos/$photoId` lightbox (people sheet, delete) · `/e/$slug/people`, `/e/$slug/people/$personId` · `/e/$slug/best` highlights · `/e/$slug/search` agent · `/e/$slug/me` redirects to `?filter=me` · `/s/$shareId` read-only album |
| Member | `/` home with greeting, fanned stacks, suggestions · `/year/$year` recap · `/people` across events · `/search`, `/search/saved` · `/albums/$albumId` album detail · `/manage` owner dashboard · `/import` · `/library` |
| Host | `/new` · `/e/$slug/settings` (face grouping toggle) · `/e/$slug/share` · `/e/$slug/uploads` · `/e/$slug/people/manage` merge and split |
| Account | `/login` · `/auth/verify` · `/settings` (name, language de/en/tr, birthday, faces, delete face data) · `/expired` |

## Layout

```
src/router.tsx, src/start.ts      framework touchpoints (QueryClient per request, SSR query integration)
src/routes                        file-based routes; e/$slug/* is the event area, api/health.ts a server route
src/components/<Name>             one folder per component, CSS Modules on tokens.css
  AgentPanel, AgentResult         the conversation and the per-kind result rendering (media, people, stat, album, clarify, empty, attachments)
  FanStack, SuggestionCard        the swipeable stack on Home and the "Also you?" card
  MediaTile, SimpleGrid           non-virtualized tiles for curated lists; PhotoGrid stays for the gallery
  ConfirmSheet, ShareSheet        a question with two answers; album share link with allow-download
src/lib/api                       openapi-fetch client typed from @yearbook/openapi, SSR cookie forwarding
src/lib/queries                   queryOptions factories; keys ['event', slug, 'media', filter], ['me', ...], ['person', id], ['album', id]
src/lib/agent.ts, fan.ts,         pure helpers under test: agent result mapping, fan geometry, dismissed suggestions, home rows
  suggestions.ts, home.ts
src/lib/upload                    pure reducer (machine.ts), queue driver, XHR transport, IndexedDB manifest; importUpload.ts reuses the transport for archives
src/lib/live                      EventSource hook and cache patching for media.* / like.changed; people.updated invalidates people, persons, counts
src/i18n                          de.ts is the source; en.ts and tr.ts must satisfy the same shape
src/styles                        tokens, reset, self-hosted fonts, global, per-page modules
```

Conventions worth knowing: gold (`--you`) only for lines about the viewer, Bodoni italics for those lines; square corners except face chips and the Me pill; every destructive action goes through `ConfirmSheet`; attachments from the agent are short-lived URLs and never cached.

## Build

`pnpm build` produces `.output/` through Nitro; `node .output/server/index.mjs` serves it. `apps/web/Dockerfile` builds from the repo root.
