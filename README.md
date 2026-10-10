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
| `apps/worker` | Python worker: variants, HEIC, EXIF, video, hashes, dedupe (faces and search come next) | background |
| `apps/web` | TanStack Start web app: landing, upload, gallery, lightbox, host pages | `:3000` |
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

It prints the event link and a sign-in link for the demo host. Magic-link emails land in Mailpit at http://localhost:8025.

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

3. Three terminals (or a tmux session):

```sh
mise run api            # http://localhost:8080, hot reload
mise run worker         # 4 processes, reload on change
mise run web            # http://localhost:3000, proxies /api to the API
```

4. Seed a demo event with the fixture photos and open the printed link:

```sh
mise run seed
```

Sign in via the printed link (or any email: the magic link is in Mailpit at http://localhost:8025 and also in the API log).

### Everyday commands

| Command | Does |
|---|---|
| `mise run test` | Go, Python and web unit tests |
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

## How a photo flows

Browser asks the API for an upload intent, PUTs the bytes straight to S3 with a presigned URL (multipart above 64 MiB, resumable), then tells the API it is done. The API queues an `ingest` job in Postgres and pushes `media.queued` over Server-Sent Events, so the grid shows a processing cell at once. A worker claims the job, probes EXIF, decodes HEIC, makes WebP variants, hashes, groups duplicates, and notifies `media.ready`; the API relays it and the cell turns into a thumbnail served from the public bucket. Details and diagrams: `docs/SDD.md` §7–8.

## Project status

M0 and M1 of the roadmap are implemented: guest upload, gallery, lightbox, likes, select + zip, live updates, magic-link login, create event, QR and share, host review. Next: import from Google Takeout and folders (M1.5), then faces and "photos of me" (M2). See `docs/SDD.md` §12.
