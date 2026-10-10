# Yearbook

A shared photo album that assembles itself. The host puts a QR code on the table, guests upload from their phone browser with no app and no account, and afterwards everyone finds the photos they are in.

- Design document: `docs/SDD.md` (diagrams regenerate with `uv run docs/diagrams/build.py`)
- Rules every app follows: `docs/CONVENTIONS.md`
- API contract: `packages/openapi/openapi.yaml`
- Agent notes for this repo: `CLAUDE.md`

## What is in the repo

| Path | What | Runs as |
|---|---|---|
| `apps/api` | Go API: auth, events, uploads, media, likes, zip, live updates | `:8080` |
| `apps/worker` | Python workers: light pipeline (variants, HEIC, EXIF, video, hashes, dedupe, imports) and ML pipeline (faces, embeddings, quality, captions, age, clustering); ML server for text search | background, `:8090` |
| `apps/web` | TanStack Start web app: landing, upload, gallery, lightbox, people, search and assistant, home, your year, manage, import | `:3000` |
| `apps/agent` | LangGraph chat assistant: talks to the API's tools over MCP and to OpenAI; keeps conversations in Postgres | `:8091` |
| `apps/sandbox` | Runs assistant-written code in throwaway, network-less containers | `:8092` |
| `packages/openapi` | The contract; Go stubs and TypeScript types are generated from it | |
| `infra` | Compose, migrations, S3 init, Caddy configs | |

## Option A: everything in containers (quickest look)

Needs Docker with Compose v2. Nothing else.

```sh
git clone <this repo> yearbook && cd yearbook
docker compose -f infra/compose.yaml --profile app up --build -d
```

Then open http://localhost:8000. To get an event to look at:

```sh
docker compose -f infra/compose.yaml --profile app run --rm --entrypoint /app/ybctl api seed --fixtures /fixtures
```

It prints the event link and a sign-in link for the demo host.

**Email in development never reaches a real inbox.** Every magic link lands in Mailpit at http://localhost:8025; open the newest message there and click the button. Production uses a real SMTP provider (Resend, Postmark) through `SMTP_HOST`, `SMTP_PORT` and `SMTP_FROM`; no code changes.

What runs: Postgres with pgvector, SeaweedFS as the S3 store (`:8333`), Mailpit, the API, two worker processes, the web server, and a Caddy gateway on `:8000` that serves the web app and routes `/api` to the API so cookies stay on one origin.

Stop with `docker compose -f infra/compose.yaml --profile app down` (add `-v` to wipe data).

## Option B: develop on the host (fast edit-run loop)

Services run in Docker, the three apps run on your machine with hot reload. Toolchains are pinned per project by [mise](https://mise.jdx.dev), so you do not install Go, Node or Python yourself.

1. Install mise once: `curl https://mise.run | sh` (or `sudo pacman -S mise` / `brew install mise`), and activate it in your shell as the installer prints. Docker must be running.
2. In the repo:

```sh
mise install            # Go 1.27, Node 26, pnpm, Python 3.12, uv, sqlc, goose, air
cp .env.example .env    # dev defaults, loaded automatically by mise
mise run up             # Postgres, SeaweedFS (+ bucket init), Mailpit
mise run migrate        # applies infra/migrations to the dev database
pnpm install            # web workspace
mise run gen            # Go + TypeScript code from openapi.yaml and the sqlc queries
cd apps/worker && uv sync && cd ../..
```

3. One terminal per process (a tmux session works well):

```sh
mise run api            # http://localhost:8080, hot reload; Swagger UI at http://localhost:8080/api/docs
mise run worker         # light pipeline: variants, dedupe, imports
mise run ml-worker      # faces, embeddings, quality, captions, age, clustering (downloads models on first run)
mise run ml             # text-embedding server for search, :8090
mise run agent          # chat assistant, :8091 (needs OPENAI_API_KEY in .env to answer)
mise run sandbox        # assistant code execution, :8092 (needs Docker)
mise run web            # http://localhost:3000, proxies /api to the API
```

Only `api`, `worker` and `web` are needed for uploading and browsing. The others switch on people, search, the assistant and its tools.

4. Seed a demo event with the fixture photos and open the printed link:

```sh
mise run seed
```

Sign in via the printed link (or any email: the magic link is in Mailpit at http://localhost:8025 and also in the API log).

### Everyday commands

| Command | Does |
|---|---|
| `mise run test` | Go, Python and web unit and integration tests |
| `mise run test:system` | System tests over HTTP and SSE against the running stack (`BASE_URL`, default :8000) |
| `mise run lint` | go vet, ruff, tsc + biome |
| `mise run gen` | regenerate after editing `openapi.yaml` or a `.sql` query |
| `mise run ci` | what GitHub Actions runs |
| `cd apps/web && pnpm test:e2e --project=pixel-7` | Playwright with a mocked API; `E2E_LIVE=1` to hit the real stack |
| `cd apps/web && node scripts/screenshots.mjs <slug>` | phone-sized screenshots of the key screens into `test-results/screens` |
| `cd apps/api && go run ./cmd/ybctl magic you@example.com` | print a sign-in link without email |
| `docker compose -f infra/compose.yaml --profile proxy up -d caddy` | optional single-origin proxy at :8000 for the host setup |

### Ports

| Port | Service |
|---|---|
| 3000 | web (host dev) |
| 8080 | API |
| 8000 | Caddy gateway (containers) or optional dev proxy |
| 8333 | S3 (SeaweedFS), public bucket readable, private bucket presigned only |
| 8025 / 1025 | Mailpit UI / SMTP |
| 5432 | Postgres (`yearbook` / `yearbook`, DBs `yearbook`, `yearbook_test`, `yearbook_test_worker`) |

## Tests, three levels

| Level | Where | Command |
|---|---|---|
| Unit | each app | `go test ./...`, `uv run pytest -m "not ml"`, `pnpm test` |
| Integration | API (real Postgres + S3), worker (real models with `-m ml`), agent (real Postgres checkpointer, fake model and MCP), sandbox (real Docker) | `mise run test` |
| System | `tests/system`: real HTTP, SSE, mail, storage and workers through the gateway; browser flows with `cd apps/web && E2E_LIVE=1 pnpm test:e2e` | `mise run test:system` |

## How a photo flows

Browser asks the API for an upload intent, PUTs the bytes straight to S3 with a presigned URL (multipart above 64 MiB, resumable), then tells the API it is done. The API queues an `ingest` job in Postgres and pushes `media.queued` over Server-Sent Events, so the grid shows a processing cell at once. A worker claims the job, probes EXIF, decodes HEIC, makes WebP variants, hashes, groups duplicates, and notifies `media.ready`; the API relays it and the cell turns into a thumbnail served from the public bucket. Details and diagrams: `docs/SDD.md` §7–8.

## Project status

Implemented: guest upload, gallery, lightbox, likes, select + zip, delete, live updates, magic-link login (de/en/tr), create event, QR and share, host review; faces and People with claim, merge and split; "photos of me" and cross-event suggestions; hybrid text search; highlights, albums and public shares; home with swipeable stacks and Your year; owner dashboard; Takeout and folder import with a personal library; privacy controls; the chat assistant with MCP tools, a guarded SQL tool, saved chips and sandboxed self-made tools; Swagger UI. Public-launch items are milestone M7 in `docs/SDD.md` §12.
