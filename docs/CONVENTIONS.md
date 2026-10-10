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

## Time grouping
`MediaPage.groups` are computed by the API in the event timezone with keys `morning` (05–11), `afternoon` (11–17), `evening` (17–22), `night` (22–05), one group per calendar day and day part, ordered newest first. The web app localizes labels.

## Dev URLs
API `http://localhost:8080`, web `http://localhost:3000` (Vite proxies `/api` to the API, so cookies are same-origin), S3 `http://localhost:8333`, Mailpit UI `http://localhost:8025`, SMTP `localhost:1025`, Postgres `localhost:5432`.
