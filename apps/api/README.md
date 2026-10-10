# Yearbook API (Go)

The HTTP API behind the web app: auth, events, presigned uploads, media listing, likes, zip
downloads, Server-Sent Events, people (face clusters), hybrid search, highlights, albums and
shares, the yearbook, imports, and the agent's tools over MCP. The contract is
`packages/openapi/openapi.yaml`; the Go stubs in `internal/gen/api` and the sqlc queries in
`internal/gen/db` are generated and committed. Swagger UI: `http://localhost:8080/api/docs`
(spec at `/api/v1/openapi.json`); "try it out" runs same-origin, so your cookies apply.

## Layout

```
cmd/api          the server
cmd/ybctl        operator CLI: migrate | seed [--fixtures DIR] | magic <email> | import <dir> --user <email> [--event <slug>]
internal/
  agent          run_query guardrails: pg_query validation, agent_ro executor, named-parameter binding
  apperr         error type + the ErrorResponse JSON shape
  auth           Principal (who is calling), sessions, magic links, rate limits, cookies
  config         environment variables (loaded from the repo .env by mise)
  db             pgx pool, goose migrations (from ../../infra/migrations)
  db/queries     sqlc input (*.sql)            -> gen/db
  gen/api        oapi-codegen output (chi + strict server + models)
  handlers       one file per concern; implements api.StrictServerInterface
  httpserver     middleware chain and router
  jobs           enqueue work for the Python worker
  mail           SMTP sender (Mailpit in dev) + recorder for tests
  media          upload rules, GridItem assembly, cursors, time-of-day groups
  middleware     logging, CORS, CSRF origin check, principal from cookies
  realtime       SSE hub, replay ring, Postgres LISTEN loop
  search         text embedder client (ML server) + the one hybrid search statement
  storage        S3 client: presign, multipart, head/get/put, zip streaming
  testutil       integration test bootstrap (real Postgres + S3)
```

## Commands

Run everything from the repo root with mise active (`mise run up` first).

```sh
mise run migrate                 # or: go run ./cmd/ybctl migrate
mise run gen                     # sqlc generate && go generate ./...  (oapi-codegen via `go tool`)
mise run api                     # air hot reload on :8080
go run ./cmd/ybctl seed --fixtures ../worker/fixtures   # demo user + event (+ queued fixture media)
go run ./cmd/ybctl magic you@example.org                # print a sign-in URL without email
go vet ./... && go test ./... -count=1                  # integration tests against TEST_DATABASE_URL
go test ./... -short                                    # skips the 65 MiB multipart upload test
```

Docker image (context is the repo root): `docker build -f apps/api/Dockerfile -t yearbook-api .`

## Environment (round 2)

| Variable | Default | Meaning |
|---|---|---|
| `ML_URL` | `http://localhost:8090` | Worker ML server; `POST /embed/text` gives SigLIP text vectors for search. Unreachable = text-only search (a warning is logged) |
| `AGENT_URL` | `http://localhost:8091` | Python LangGraph agent service (`apps/agent`). `POST /agent/messages`, `POST /agent/commands`, `POST /media/{id}/describe` and python chip runs are proxied there; unreachable = `503 agent_not_configured` |
| `AGENT_DB_PASSWORD` | `agent-ro-dev` | Password of `agent_ro_login`, the login role `ybctl migrate` creates inside the nologin role `agent_ro`. `run_query` connects with it over a dedicated pool (`AGENT_DB_URL` overrides the whole URL) |
| `OPERATOR_EMAIL` | empty | The one account allowed to start folder imports from a server path (`POST /imports` with `kind=folder`) |

Agent tools live in Go and are served over MCP (streamable HTTP) at `/mcp`:
`resolve_people`, `search_media`, `rank_best`, `list_people`, `describe_media` (metadata only),
`create_album`, `like_media`, `share_album`, `export_zip`, `event_stats`, `run_query`,
`run_saved_command`. Auth is `Authorization: Bearer <yb_session token or yb_guest id>`;
`X-Event-Slug` scopes the tools to one event. `run_query` accepts exactly one `SELECT` over the
`v_*` views, parsed with pg_query against a function allowlist (`internal/agent/sqlguard.go`),
executed as `agent_ro` inside a read-only transaction with `statement_timeout = 2 s`, capped at
500 rows / 64 KB. Saved commands of kind `sql` and `search` run in Go with bind parameters and no
model call; kind `python` is proxied to the agent service.

## Trying it with curl

Mutations need an `Origin` from `ALLOWED_ORIGINS` (CSRF rule from docs/CONVENTIONS.md).

```sh
O='Origin: http://localhost:3000'; J='Content-Type: application/json'
curl -s -XPOST :8080/api/v1/auth/magic -H "$O" -H "$J" -d '{"email":"you@example.org"}'
# the link is in Mailpit (http://localhost:8025) and in the API log; take its token
curl -s -c c.txt -XPOST :8080/api/v1/auth/verify -H "$O" -H "$J" -d '{"token":"..."}'
curl -s -b c.txt -XPOST :8080/api/v1/events -H "$O" -H "$J" -d '{"title":"Sommerfest","starts_at":"2026-10-10T18:00:00Z"}'
curl -s :8080/api/v1/events/<slug>/qr.svg -o qr.svg
curl -s -c g.txt -XPOST :8080/api/v1/events/<slug>/guests -H "$O"               # guest cookie
curl -s -b g.txt -XPOST :8080/api/v1/events/<slug>/uploads -H "$O" -H "$J" \
  -d '{"files":[{"client_id":"1","name":"a.jpg","size":12345,"type":"image/jpeg"}]}'
curl -T a.jpg -H 'Content-Type: image/jpeg' "<url from the intent>"
curl -s -b g.txt -XPOST :8080/api/v1/uploads/<media_id>/complete -H "$O"
curl -N :8080/api/v1/events/<slug>/events                                         # SSE
curl -s -b g.txt -XPUT :8080/api/v1/media/<media_id>/like -H "$O"
curl -s -b g.txt -XPOST :8080/api/v1/media/zip -H "$O" -H "$J" -d '{"media_ids":["<id>"]}'

# round 2
curl -s -b g.txt :8080/api/v1/events/<slug>/people                                # face clusters, suggested_me
curl -s -b g.txt -XPOST :8080/api/v1/people/<person_id>/claim -H "$O"             # "This is me"
curl -s -b g.txt ':8080/api/v1/events/<slug>/media?filter=me'                     # photos of you
curl -s -b g.txt ':8080/api/v1/events/<slug>/search?q=torte'                      # hybrid search
curl -s -b g.txt ':8080/api/v1/events/<slug>/best?limit=12'                       # highlights
curl -s -b g.txt -XPOST :8080/api/v1/albums -H "$O" -H "$J" -d '{"event_slug":"<slug>","title":"Auswahl","media_ids":["<id>"]}'
curl -s -b g.txt -XPOST :8080/api/v1/albums/<album_id>/share -H "$O" -H "$J" -d '{"allow_download":false}'
curl -s :8080/api/v1/s/<share_id>                                                 # public album
curl -s -b c.txt :8080/api/v1/me/years && curl -s -b c.txt :8080/api/v1/me/years/2026
curl -s -b c.txt -XPOST :8080/api/v1/imports -H "$O" -H "$J" -d '{"kind":"takeout","filename":"takeout.zip","size":123456}'
curl -s -b c.txt -XPOST :8080/api/v1/imports/<import_id>/complete -H "$O"
curl -s -b c.txt ':8080/api/v1/me/library?unassigned=true'
curl -s -b c.txt -XPOST :8080/api/v1/agent/messages -H "$O" -H "$J" -d '{"text":"Fotos von mir und Anna","event_slug":"<slug>"}'
curl -s -b c.txt ':8080/api/v1/agent/commands?event_slug=<slug>'
curl -s -b c.txt -XPOST :8080/api/v1/agent/commands/<command_id>/run -H "$O" -H "$J" -d '{"params":{"n":5}}'
curl -s :8080/api/v1/openapi.json | head -c 200                                   # spec; UI at /api/docs

# MCP (the yb_session cookie value is the bearer token; guests use their yb_guest id)
curl -s :8080/mcp -H 'Authorization: Bearer <token>' -H 'X-Event-Slug: <slug>' \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"run_query","arguments":{"sql":"select count(*) from v_media"}}}'
```

## Notes for the Go learner

- Handlers return `error`; `apperr.Write` turns an `*apperr.Error` into the contract's JSON and
  anything else into a logged 500. There is no error handling boilerplate in the handlers.
- The strict server gives handlers typed requests and responses. Where the generated response
  type cannot express what we need (cookies, a 302 Location, a never-ending SSE stream) a small
  struct with a `Visit…Response` method takes over; see `handlers/sse.go`.
- `viewerFor` resolves the caller's role in an event once per request; all permission checks
  read from that value.
- Ids are `[]byte` in Go and `bytea` in Postgres; `ids.Encode`/`ids.Decode` convert at the edge.
