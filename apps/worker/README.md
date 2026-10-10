# Yearbook worker

Python 3.12 process that claims `ingest` jobs from the Postgres `jobs` table, downloads the
original from the private bucket, and produces everything the grid needs: dimensions, capture
time, orientation, GPS, WebP variants (`thumb`, `small`, `medium`, `large`), H.264 + poster
for videos, SHA-256 and pHash, and duplicate groups. Stages record themselves in
`media.processed_stages`, so a crash resumes instead of restarting.

Later rounds add faces, embeddings, quality and tags as further stages behind the same loop.

## Run

From the repo root, `eval "$(mise activate bash)"` (or the fish equivalent) loads the toolchain
and `.env`. Then in `apps/worker`:

```sh
uv sync                                   # create .venv from uv.lock
uv run yearbook-worker run --concurrency 4  # 4 processes, LISTEN jobs_new + 5 s poll
uv run yearbook-worker run --kinds ingest,noop
uv run yearbook-worker ingest <media_id>  # run the pipeline for one media row, no job
uv run yearbook-worker ingest <media_id> --reset   # clear processed_stages first
uv run yearbook-worker once <job_id>      # take over one job regardless of its lock
mise run worker                           # same as `run`, restarting on source changes
```

Logs are one JSON object per line; every stage emits `{"event": "stage.done", "media_id",
"stage", "duration_ms"}`.

## Test and lint

```sh
uv run ruff check .
uv run pytest -q                 # unit + integration (needs TEST_DATABASE_URL and S3 from .env)
uv run pytest -q -m "not integration"
uv run python fixtures/generate.py   # regenerate the committed fixture set
```

Integration tests truncate the test database (`yearbook_test`) and write under
`v/<random prefix>/` in the public bucket.

## Configuration

Shared keys from `docs/CONVENTIONS.md`: `DATABASE_URL`, `S3_ENDPOINT`, `S3_REGION`,
`S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_FORCE_PATH_STYLE`, `S3_BUCKET_PRIVATE`,
`S3_BUCKET_PUBLIC`, `PUBLIC_BASE_URL`. Worker-only, all optional:

| Key | Default | Meaning |
|---|---|---|
| `WORKER_CONCURRENCY` | `4` | processes started by `run` |
| `WORKER_KINDS` | `ingest` | comma separated job kinds to claim |
| `WORKER_POLL_SECONDS` | `5` | poll interval when no `NOTIFY jobs_new` arrives |
| `WORKER_HEARTBEAT_SECONDS` | `30` | `locked_at` refresh while a job runs |
| `WORKER_TMP_DIR` | system temp | where originals are downloaded while processing |
| `WORKER_LOG_LEVEL` | `INFO` | |
| `DEFAULT_TIMEZONE` | `Europe/Berlin` | used when a media row has no event |

## Layout

```
src/yearbook_worker/
  cli.py          run | once | ingest
  worker.py       claim → heartbeat → dispatch → complete/fail; multiprocessing supervisor
  queue.py        jobs table SQL exactly as pinned in CONVENTIONS
  pipeline.py     run_ingest: stage loop, resume, state transitions, NOTIFY
  context.py      MediaRow, ProbeResult, VariantInfo, StageContext
  capture_time.py EXIF / filename / ISO capture-time parsing
  stages/         fetch, probe, decode, video, variants, hashes, dedupe
  storage.py      boto3 (path style, checksums when_required), stream download with sha256
  notify.py       pg_notify media_events
  heartbeat.py    lock refresh thread
fixtures/         generated test set, see fixtures/README.md; private/ is gitignored
tests/
```

## Pipeline

`fetch → probe → decode (photo) | video → variants → hashes → dedupe`

- `fetch` always runs (the original is needed on disk); it is not recorded.
- Every other stage writes its rows and `processed_stages || {name: now()}` in one transaction
  and is skipped when its key exists. `decode` and `video` have a cheap `restore` that rebuilds
  the in-memory working image on a resume.
- The end sets `state = ready`, `processed_at`, and `NOTIFY media_events {media.ready}`. A
  failure re-raises so the job backs off; on the final attempt the row becomes `failed` with
  `error` and `media.failed` is emitted. Between retries the row goes back to `queued`.
- `gps` is stored as `point(lon, lat)` (x = longitude, y = latitude).
- Dedupe scope is the event, or the owner's library when `event_id` is null. Exact = same
  SHA-256; near = pHash Hamming distance ≤ 6 and capture times within 120 s. The largest file
  of a group keeps `is_best_of_dup = true`; the others stay `ready` but hidden from the grid.

## Docker

```sh
docker build -t yearbook-worker apps/worker
docker run --env-file .env yearbook-worker            # run --concurrency $WORKER_CONCURRENCY
```
