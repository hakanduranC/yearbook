# Yearbook API (Go)

The HTTP API behind the web app: auth, events, presigned uploads, media listing, likes, zip
downloads and Server-Sent Events. The contract is `packages/openapi/openapi.yaml`; the Go stubs
in `internal/gen/api` and the sqlc queries in `internal/gen/db` are generated and committed.

## Layout

```
cmd/api          the server
cmd/ybctl        operator CLI: migrate | seed [--fixtures DIR] | magic <email>
internal/
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
