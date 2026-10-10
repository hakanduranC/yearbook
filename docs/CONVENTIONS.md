# Cross-app conventions (binding for api, worker, web)

Read `docs/SDD.md` for the design and `packages/openapi/openapi.yaml` for the contract. This file pins the details the three apps must agree on byte for byte.

## Ids
16 random bytes. Wire format: base64url without padding, always 22 characters. Go: `base64.RawURLEncoding`. Python: `base64.urlsafe_b64encode(b).rstrip(b"=")`. Database columns are `bytea`.

## Environment
Loaded from `.env` at the repo root (mise does this automatically). Keys: `DATABASE_URL`, `TEST_DATABASE_URL`, `S3_ENDPOINT`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_FORCE_PATH_STYLE`, `S3_BUCKET_PRIVATE`, `S3_BUCKET_PUBLIC`, `PUBLIC_BASE_URL`, `API_ADDR`, `WEB_ORIGIN`, `ALLOWED_ORIGINS`, `COOKIE_SECURE`, `SESSION_SECRET`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `API_INTERNAL_URL`, `PUBLIC_WEB_ORIGIN`.
S3 clients must set path-style addressing and `request_checksum_calculation = when_required` / `response_checksum_validation = when_required` (SeaweedFS and R2 reject the SDK defaults otherwise). Both buckets exist with CORS applied; see `infra/s3`.

## Object keys
- Private bucket: originals `o/{event_id_or_lib}/{media_id}.{ext}` where the segment is the event id or the literal `lib` for library items. Face crops later under `f/`.
- Public bucket: `v/{variant_prefix}/thumb.webp` (256 square, center crop), `small.webp` (640 long edge), `medium.webp` (1280), `large.webp` (2048), `poster.webp` (videos, 1280), `video.mp4` (H.264, 1080p max). `variant_prefix` is a 22-char id stored on `media`.
- Public URL = `PUBLIC_BASE_URL + "/" + key`.

## Media lifecycle
`uploading` (intent created) → `queued` (complete verified, `ingest` job inserted) → `processing` (worker claimed) → `ready` | `failed`. `removed` is a tombstone with `removed_at`. `media.processed_stages` is a JSON object `{stage_name: iso_timestamp}`; a stage is skipped when its key exists.

## Jobs table protocol (worker side, Postgres)
`locked_by = "{host}:{pid}:{uuid}"`. Claim with `FOR UPDATE SKIP LOCKED` on `done_at is null and run_after <= now() and (locked_at is null or locked_at < now() - interval '2 minutes')`, ordered by `priority desc, run_after, id`, setting `locked_by, locked_at = now(), attempts = attempts + 1`. Heartbeat refreshes `locked_at` every 30 s. Complete sets `done_at = now(), locked_by = null, error = null`. Fail sets `locked_by = null, locked_at = null, error`, `run_after = now() + least(600, 10 * 2^attempts) seconds`, and `done_at = now()` only when `attempts >= max_attempts` (dead). The API enqueues `ingest` with payload `{"media_id": "<22-char id>"}`; a trigger emits `NOTIFY jobs_new`.

## Postgres NOTIFY channel `media_events`
Payload is JSON: `{"type": "media.ready" | "media.failed", "event_id": "<id or null>", "media_id": "<id>"}`. The worker emits these; the API listens and turns them into SSE events, loading the full `GridItem` for `media.ready`. The API emits its own `media.queued`, `media.removed`, `like.changed` directly to its SSE hub (it may also go through NOTIFY so multiple API replicas work).

## SSE (`GET /api/v1/events/{slug}/events`)
`event:` name, `data:` JSON, `id:` monotonically increasing per event, `retry: 5000`, comment ping every 20 s. Names and payloads: `media.queued {id, mine}`, `media.ready GridItem`, `media.failed {id, code}`, `media.removed {id}`, `like.changed {media_id, like_count}`, `people.updated {event_slug}`. Headers: `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`. Never gzip this response.

## Cookies
`yb_session`: 32 random bytes base64url; server stores sha256 in `sessions.token_hash`; HttpOnly, SameSite=Lax, Path=/, Secure when `COOKIE_SECURE=true`, 90 days sliding. `yb_guest`: the 22-char `guest_cookies.id`; HttpOnly, SameSite=Lax, Path=/, 1 year. Set only by `POST /events/{slug}/guests` (and reused on later events). Mutations require an `Origin` header in `ALLOWED_ORIGINS` or `Sec-Fetch-Site: same-origin`.

## Coordinates
`media.gps` is a Postgres `point(longitude, latitude)`, x = longitude. Any reader must keep that order.

## Media retries
While a failed `ingest` job waits for its backoff retry, the worker sets `media.state` back to `queued` so the grid keeps showing a processing cell; only a dead job yields `failed`.

## Time grouping
`MediaPage.groups` are computed by the API in the event timezone with keys `morning` (05–11), `afternoon` (11–17), `evening` (17–22), `night` (22–05), one group per calendar day and day part, ordered newest first. The web app localizes labels.

## Dev URLs
API `http://localhost:8080`, web `http://localhost:3000` (Vite proxies `/api` to the API, so cookies are same-origin), S3 `http://localhost:8333`, Mailpit UI `http://localhost:8025`, SMTP `localhost:1025`, Postgres `localhost:5432`.

---

# Round 2 additions (faces, search, agent, import)

## Job kinds
| Kind | Payload | Who runs it | What |
|---|---|---|---|
| `ingest` | `{media_id}` | light worker | as before; at the end enqueues `analyze` for the same media |
| `analyze` | `{media_id}` | ML worker (`yearbook-worker run --kinds analyze`, concurrency 1–2, models loaded once) | faces (only if `events.faces_enabled`, always for library items of a user), SigLIP embedding, quality + aesthetic, tags/OCR, age; sets `media.analyzed_at`; NOTIFY `media_events {type: media.analyzed, event_id, media_id}`; then enqueues a debounced `cluster_event` |
| `cluster_event` | `{event_id}` | ML worker | incremental assignment + HDBSCAN per SDD §8.2; respects `person_constraints`; sets `events.clustered_at`; NOTIFY `media_events {type: people.updated, event_id}` |
| `import` | `{import_id}` | light worker | reads the archive or folder, writes originals + media rows, enqueues `ingest` per item, updates `imports.stats`, state → done/failed |
| `recompute_scores` | `{event_id}` | light worker | refreshes `media_quality.score` after likes change (batched by the API, debounced 60 s) |

Debounced enqueue (cluster_event, recompute_scores): `insert into jobs (kind, payload, run_after) select $1, $2, now() + interval '60 seconds' where not exists (select 1 from jobs where kind = $1 and payload->>'event_id' = $3 and done_at is null)`.

## NOTIFY `media_events` types
`media.ready`, `media.failed`, `media.analyzed`, `people.updated` (event_id), `import.progress` (import_id, stats, state). The API relays `people.updated {event_slug}` on the event SSE stream. Import progress is polled by the web app (`GET /imports/{id}` every 3 s while running).

## Models and vectors
Face embeddings: ArcFace 512-d (InsightFace `antelopev2`), L2-normalized. Image embeddings: SigLIP 2 `so400m` family, 1152-d, L2-normalized, stored in `media_embeddings` (column is `vector(1152)`; do not switch to a 768-d model without a migration). Text embeddings for search come from the same SigLIP 2 text tower.

## ML server
`yearbook-worker serve --port 8090` (FastAPI inside the worker package) exposes `GET /health` and `POST /embed/text {"texts": [...]} -> {"vectors": [[...]], "model": "..."}`. The API reads `ML_URL` (default `http://localhost:8090`); when unreachable, text search falls back to full-text + tags only and reports `degraded: true` is not in the contract, so just log a warning.

## Hybrid search (API)
One SQL: candidates = top 200 by cosine on `media_embeddings` ∪ `caption_tsv @@ websearch_to_tsquery` ∪ `media_tags.tag % q`; fuse with reciprocal rank fusion (k = 60); apply structured filters; return as `MediaPage` ordered by fused score.

## Quality score
`score = 0.35*aesthetic_norm + 0.25*sharpness + 0.15*faces_term + 0.15*eyes_smile + 0.10*likes_norm`, each term 0..1, `faces_term = 1` for 1–6 faces, 0.6 for 0, 0.4 for more than 6. `aesthetic_norm = clamp((aesthetic-3)/5)`. `likes_norm = likes / max(likes in event)`. Highlights (`/events/{slug}/best`): top N by score, one per duplicate group, at most 3 per 30-minute window until N is filled.

## Face crops
Private bucket `f/{face_id}.jpg`, 20 % padded, max 512 px. Served only by `GET /api/v1/faces/{face_id}/crop.jpg` with `Cache-Control: private, max-age=86400`.

## Person suggestions
`suggested_me` inside an event: the person with the most faces among photos uploaded by the viewer's guest/user, if it has ≥ 3 faces and ≥ 2× the runner-up. Cross-event (`GET /me/suggestions`): reference set = up to 30 best faces of the identity's claimed persons; candidate persons in the user's other events with max cosine ≥ 0.45; if a birthdate is known and the capture years differ by more than 8 from the reference, require `|age_est − exact_age| ≤ 6`.

## Age filters
`age_min`/`age_max` on media lists and `search_media`: exact when the person is linked to an identity with a birthdate (`captured_at::date − birthdate`), else `faces.age_est`. Results carry no age numbers per face in public payloads.

## Agent service split
The language-model loop lives in `apps/agent` (Python, LangGraph). The Go API authenticates the user and proxies `POST /agent/messages`, `POST /agent/commands` and `POST /media/{id}/describe` to `AGENT_URL` (default `http://localhost:8091`) with headers `X-Actor` (base64url id), `X-Actor-Kind` (user|guest), `X-Event-Slug`, `X-Locale`, `X-Session-Token` (raw cookie value). The agent service calls the API's MCP endpoint `/mcp` with `Authorization: Bearer <that token>` and `X-Event-Slug`, so every tool runs as the same principal under the same visibility rules. Go keeps the tool implementations, the `run_query` guardrails, saved-command storage and execution (`GET/DELETE /agent/commands`, `POST /agent/commands/{id}/run`). Connection failures to the agent service surface as 503 `agent_not_configured`.

## Agent
Env: `OPENAI_API_KEY`, `OPENAI_MODEL` (an exact model id; when empty the agent service resolves the newest GPT-6 family chat model from `GET /v1/models`, falling back to GPT-5 only if none is available, and logs the choice), `OPENAI_BASE_URL` optional. Without a key `POST /agent/messages` returns `503 {code: internal, message: "agent_not_configured"}` and the web app shows a calm message. Only text and metadata are sent; `POST /media/{id}/describe` is the single user-initiated image exception. `run_query` executes as role `agent_ro` over the `v_*` views with `SET LOCAL app.actor = '<base64 of actor id>'`, `SET LOCAL app.event = '<base64 of event id or empty>'`, `statement_timeout = 2000`, row cap 500.

## Import archives
Zip or Takeout archives go to the private bucket under `imports/{import_id}.zip` via the same presigned multipart flow as media. Takeout layout: `Takeout/Google Photos/<album>/<file>` with sidecars `<file>.json` or `<file>.supplemental-metadata.json` (and truncated variants) holding `photoTakenTime.timestamp`, `geoData`, `people[].name`. Matching to events: `captured_at` within `[starts_at − 2 h, coalesce(ends_at, starts_at + 12 h) + 2 h]` of one of the owner's events; otherwise the item stays in the library (`event_id null`). People names from sidecars are stored in `media_person_hints` and applied as person display names when a cluster has ≥ 3 faces whose media share the same hint.

## Locales
`de`, `en`, `tr` everywhere: `users.locale`, magic-link emails, web dictionaries, agent `understood` lines (the agent answers in the user's locale).

## Sandbox (agent-created tools)
`apps/sandbox` is a small service (`SANDBOX_URL`, default `http://localhost:8092`) and the only component allowed to start containers. `POST /run {code, inputs, files?: [{name, url}], timeout_s<=20}` runs the code in a fresh container from the pinned image `yearbook-sandbox` (python 3.12, numpy, pandas, pillow, matplotlib): `--network none`, read-only root, tmpfs `/work` 256 MB, 512 MB RAM, 1 CPU, non-root, pids limit 64, seccomp default, killed at the timeout. `inputs` is written to `/work/inputs.json`; files are fetched by the sandbox service beforehand (only URLs under `PUBLIC_BASE_URL` or presigned private URLs the API issued) into `/work/in/`; the program writes results to stdout (JSON) and files to `/work/out/`. The service returns `{exit_code, stdout, stderr, files: [{name, bytes_b64|key}]}`; the agent service uploads output files to the private bucket under `agent/{turn_id}/` and returns 1-hour presigned URLs as `attachments`. Every run is logged in `sandbox_runs`. Agent tools: `run_python(code, inputs, media_ids?)`, `create_tool(name, description, params_schema, code)` → `saved_commands(kind='python', created_by_agent=true, approved_at=null until the owner approves in the UI; the creator may run it unapproved)`, `run_tool(command_id, params)`. Production: the same containers under gVisor (`runsc`) on the VPS; Kata or Firecracker via a Kubernetes RuntimeClass later. LangSmith tracing is optional: `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT=yearbook`.
