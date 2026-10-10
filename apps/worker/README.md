# Yearbook worker

Python 3.12 processes that claim jobs from the Postgres `jobs` table. One package, three roles:

| Role | Command | Jobs |
|---|---|---|
| Light worker | `yearbook-worker run --kinds ingest,import,recompute_scores --concurrency 4` | originals → variants, hashes, duplicate groups (`ingest`); Takeout / zip / folder imports (`import`); score refresh after likes (`recompute_scores`) |
| ML worker | `yearbook-worker run --kinds analyze,cluster_event --concurrency 1` | faces, image embedding, quality, age, caption + OCR tags (`analyze`); faces → persons (`cluster_event`). Models load once per process, lazily, on the first job |
| ML server | `yearbook-worker serve --port 8090` | `GET /health`, `POST /embed/text` (SigLIP 2 text tower) for the API's hybrid search |

`ingest` enqueues `analyze` for the same media at its end; `analyze` debounces one
`cluster_event` per event (60 s). Every stage records itself in `media.processed_stages`, so a
crash resumes instead of restarting. Everything is CPU only.

## Run

From the repo root, `eval "$(mise activate bash)"` (or the fish equivalent) loads the toolchain
and `.env`. Then in `apps/worker`:

```sh
uv sync                                                        # create .venv from uv.lock
uv run yearbook-worker run --kinds ingest,import               # light worker (4 processes)
uv run yearbook-worker run --kinds analyze,cluster_event --concurrency 1   # ML worker
uv run yearbook-worker serve --port 8090                       # ML server
uv run yearbook-worker ingest <media_id> [--reset]             # one media through ingest, no job
uv run yearbook-worker analyze <media_id> [--reset] [--only faces,age]   # one media through analysis
uv run yearbook-worker recluster <event slug|id>               # full recluster now
uv run yearbook-worker eval-cluster --event <slug|id> --labels fixtures/faces/labels.json
uv run yearbook-worker import <import_id>                      # one import, no job
uv run yearbook-worker once <job_id>                           # take over one job regardless of its lock
mise run worker                                                # light worker, restarting on changes
```

Logs are one JSON object per line; every stage emits `{"event": "stage.done", "media_id",
"stage", "duration_ms"}`, `analyze.done` carries `stages_ms`, `cluster.done` the run statistics.

## Test and lint

```sh
uv run ruff check .
uv run pytest -q -m "not ml"     # unit + integration (Postgres + S3 from .env), ~35 s
uv run pytest -q -m ml -s        # real models on fixtures/faces, several minutes, downloads first
uv run pytest -q                 # everything
uv run python fixtures/generate.py      # regenerate the synthetic fixtures + takeout.zip
uv run python fixtures/fetch_faces.py   # refetch the portrait fixtures from Wikimedia Commons
```

Integration tests truncate `WORKER_TEST_DATABASE_URL` (fallback `TEST_DATABASE_URL`) and write
under `v/<random prefix>/`, `f/` and `imports/` in the dev buckets.

## Configuration

Shared keys from `docs/CONVENTIONS.md`: `DATABASE_URL`, `S3_ENDPOINT`, `S3_REGION`,
`S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_FORCE_PATH_STYLE`, `S3_BUCKET_PRIVATE`,
`S3_BUCKET_PUBLIC`, `PUBLIC_BASE_URL`. Worker-only, all optional:

| Key | Default | Meaning |
|---|---|---|
| `WORKER_CONCURRENCY` | `4` | processes started by `run` (use 1 for the ML kinds) |
| `WORKER_KINDS` | `ingest` | comma separated job kinds to claim when `--kinds` is absent |
| `WORKER_POLL_SECONDS` | `5` | poll interval when no `NOTIFY jobs_new` arrives |
| `WORKER_HEARTBEAT_SECONDS` | `30` | `locked_at` refresh while a job runs |
| `WORKER_TMP_DIR` | system temp | where originals, variants and archives are staged |
| `WORKER_LOG_LEVEL` | `INFO` | |
| `DEFAULT_TIMEZONE` | `Europe/Berlin` | used when a media row has no event |
| `WORKER_MODELS_DIR` | `apps/worker/.cache` (`/models` in Docker) | model cache: `hf/` (HF_HOME) and `insightface/` below it |
| `WORKER_TAGS_ENABLED` | `true` | run the Florence-2 caption + OCR stage |
| `WORKER_SIGLIP_MODEL` | `google/siglip2-so400m-patch14-384` | image + text embeddings; any so400m checkpoint (1152-d) works, see timings |
| `WORKER_FLORENCE_MODEL` | `florence-community/Florence-2-base` | caption + OCR |
| `WORKER_AGE_MODEL` | `iitolstykh/mivolo_v2` | age estimation |
| `WORKER_FACE_PACK` | `antelopev2` | InsightFace pack (downloaded from the model zoo) |
| `WORKER_FACE_DET_SIZE` | `640` | detector input |
| `WORKER_FACE_DET_THRESH` | `0.6` | faces below this detector score are dropped |
| `WORKER_FACE_MIN_SIDE` | `32` | faces smaller than this (original pixels) are dropped |
| `WORKER_CLUSTER_DEBOUNCE_SECONDS` | `60` | delay of the `cluster_event` job after an analysis |
| `WORKER_CAPTION_MAX_TOKENS` | `96` | Florence-2 caption length |
| `WORKER_TORCH_THREADS` | all cores | torch intra-op threads |
| `ML_PORT` | `8090` | `serve` port |

## Layout

```
src/yearbook_worker/
  cli.py          run | serve | once | ingest | analyze | recluster | eval-cluster | import
  worker.py       claim → heartbeat → dispatch → complete/fail; multiprocessing supervisor
  queue.py        jobs table SQL exactly as pinned in CONVENTIONS (incl. debounced enqueue)
  pipeline.py     run_ingest: fetch → probe → decode | video → variants → hashes → dedupe
  analysis.py     run_analyze: faces → embed → quality → age → tags, resumable, from the `large` variant
  clustering.py   cluster_event: incremental assignment + HDBSCAN, constraints, hints, eval
  importer.py     import: zip / Takeout / folder → originals, media rows, hints, ingest jobs
  scoring.py      media_quality.score SQL (CONVENTIONS formula), recompute_scores job
  mlserver.py     FastAPI: GET /health, POST /embed/text
  models.py       lazy per-process model hub (InsightFace, SigLIP 2, Florence-2, MiVOLO)
  mivolo.py       MiVOLO v2 as a plain timm VOLO (no remote code)
  stages/         fetch, probe, decode, video, variants, hashes, dedupe, faces, embed, quality, age, tags
  storage.py      boto3 (path style, checksums when_required)
  notify.py       pg_notify media_events (media.ready/failed/analyzed, people.updated, import.progress)
fixtures/         synthetic set + takeout.zip (generate.py), portraits (fetch_faces.py)
tests/            unit (no models), integration (Postgres + S3), ml (real models)
```

## Analysis pipeline

Runs on the public `large` variant (poster frame for videos), never on the original.

- `faces`: InsightFace antelopev2 (SCRFD-10GF detector, 2d106 landmarks, ArcFace glint-R100).
  Keeps det_score ≥ 0.6 and min side ≥ 32 px; writes `faces` rows with bbox and the 5 key
  points in original pixels, 512-d L2-normalised embeddings, `eyes_open` (eye aspect ratio),
  `smile` (mouth width vs. inter-ocular distance + corner lift), `quality` (detector score,
  size, crop sharpness) and a 20 % padded JPEG crop at `f/{face_id}.jpg` in the private bucket.
  Skipped (recorded, no rows) when the event has `faces_enabled = false`; library items are
  always processed.
- `embed`: SigLIP 2 so400m vision tower → `media_embeddings` (1152-d, L2-normalised, model name).
- `quality`: sharpness (Laplacian variance of the 640 px grayscale, log-scaled to 0..1), exposure
  (clipping and mean luminance of the histogram), face terms, and **aesthetic as a proxy**:
  aesthetic-predictor-v2.5 is a head trained on SigLIP v1 features and does not transfer to
  the SigLIP 2 space stored here, so `aesthetic` is `3 + 5·(0.40·sharpness + 0.25·exposure +
  0.20·mean face quality + 0.15·expression)` on the predictor's 1..10 scale. Then `score` per
  CONVENTIONS (`scoring.py`), `likes_norm` relative to the event (or the owner's library).
- `age`: MiVOLO v2 per face crop (face input only, `body_bbox` stays null). `age_est_sd` is a
  spread, not a model output: 4 years (the model's published MAE range) widened for small or
  low-quality faces.
- `tags`: Florence-2 base `<MORE_DETAILED_CAPTION>` → `media.caption` and content words →
  `media_tags(source='florence')`; `<OCR>` words ≥ 3 chars → `media_tags(source='ocr')`.
  Greedy decoding, last in the order because it is the slowest. `WORKER_TAGS_ENABLED=false`
  skips it.
- End: `media.analyzed_at = now()`, `NOTIFY media_events {media.analyzed}`, debounced
  `cluster_event` when faces ran for an event item. Each stage commits on its own.

## Clustering

`cluster_event {event_id}` per SDD §8.2: unassigned faces join the nearest person centroid at
cosine ≥ 0.52 with margin ≥ 0.05 (quality < 0.4 only at ≥ 0.6); the rest goes through HDBSCAN
(scikit-learn, `min_cluster_size` 2, euclidean on unit vectors, members below 0.45 to their
centroid dropped as noise). A full recluster runs when more than 25 % of the faces are new since
`events.clustered_at` (or on `recluster` / `--force`), with clusters mapped to existing person
ids by maximum overlap. `person_constraints` are applied on top (must_link merges, cannot_link
moves the weaker face to a new person). Persons get `face_count`, a quality-weighted centroid,
the best frontal cover face (`cover_face_quality`), `updated_at`; empty unnamed persons are
deleted; unnamed persons with ≥ 3 faces sharing one Takeout name hint take that name. Then
`events.clustered_at` and `NOTIFY people.updated`.

`eval-cluster` reports purity, completeness and cluster count against `{face_id | filename:
label}` labels; on the portrait fixtures it gives purity 1.0 / completeness 1.0 on the eight
labelled singles (16 faces, 5 persons: the four labelled people plus one group of three small
crew faces from the 800 px STS-47 photo, which is where the thresholds should be tuned next).

## Imports

`import {import_id}`: `imports.kind` zip / takeout → the archive `imports/{id}.zip` is streamed
from the private bucket to a temp file and read with `zipfile` entry by entry; folder → walks
`source_key` on disk. Per image / video in the upload MIME allowlist: Takeout sidecars
(`<file>.json`, `<file>.supplemental-metadata.json`, numbered and truncated variants) give
`captured_at` (`captured_src = sidecar`, kept by probe), GPS and people names
(`media_person_hints`); exact SHA-256 duplicates against the owner's media (and within the
import) are skipped and counted; items match an event by the CONVENTIONS window
(`[starts_at − 2 h, coalesce(ends_at, starts_at + 12 h) + 2 h]`) unless the import has a fixed
event; originals go to `o/{event|lib}/{media_id}.{ext}`, rows to `media` (`source` takeout /
folder; plain zips are `upload`), one `ingest` job each. `imports.stats` is updated every 20
items and at the end with `NOTIFY import.progress`; state ends `done` or `failed`.

## Models

| Model | Weights | Size | License | Notes |
|---|---|---|---|---|
| InsightFace `antelopev2` | GitHub model zoo zip | 344 MB | **non-commercial** (InsightFace model pack terms; SDD §8.1 plans AdaFace for public launch) | ORT CPU sessions with spinning disabled |
| SigLIP 2 `google/siglip2-so400m-patch14-384` | HF | 4.5 GB fp32 safetensors (both towers) | Apache-2.0 | vision tower in the ML worker, text tower in the ML server |
| Florence-2 `florence-community/Florence-2-base` | HF | 0.9 GB | MIT | transformers-native port of microsoft/Florence-2-base |
| MiVOLO v2 `iitolstykh/mivolo_v2` | HF | 115 MB | Apache-2.0 (model card); the reference code on GitHub carries the authors' own non-commercial license, which is why `mivolo.py` is a timm-based re-implementation | face-only input here |

First run downloads ~6 GB into `WORKER_MODELS_DIR`; at ~15 MB/s that is 6–7 minutes. Loading
from a warm cache: InsightFace 3 s, SigLIP vision 15 s, text 8 s, Florence 2 s, MiVOLO 2 s.

## Timings (16-thread laptop i7-1360P, CPU only, throttled)

Measured with `uv run pytest -s -m ml` on the portrait fixtures (800 px files, so the `large`
variant is the full image):

| Stage | Measured | Notes |
|---|---|---|
| faces | 2.5–3.0 s for one face, 10 s for six | detection 0.4 s + ArcFace R100 ~1.2 s per face + landmarks; batching does not help on this CPU |
| embed | 5.5–8 s per image | SigLIP 2 so400m at 384 px. `google/siglip2-so400m-patch14-224` (same family, 1152-d) measured 1.9–2.8 s per image and 0.6 s per text; set `WORKER_SIGLIP_MODEL` for both the ML worker and the ML server if that trade is right for the pilot |
| quality | 30–70 ms | |
| age | 0.9–2.0 s for one face, 5.7 s for six | MiVOLO v2 |
| tags | 13–31 s per image (avg 20 s) | caption (96 tokens, greedy) + OCR with Florence-2 base; `WORKER_TAGS_ENABLED=false` to skip |
| whole `analyze` | 22–44 s per portrait (avg 36 s incl. model loads) | |
| cluster_event | < 1 s for 20 faces | |
| `/embed/text` | 0.85 s per request after warm-up | |

ML worker resident set: 3.9 GB max RSS with InsightFace, SigLIP vision, MiVOLO and Florence
loaded (measured in the test process); the ML server with only the text tower about 2.4 GB.
A VPS core is usually faster per thread than this throttled laptop, and the two heavy stages
(embed, tags) are the ones to trade down first (224 checkpoint, tags off or Florence on fewer
items).

## Docker

```sh
docker build -t yearbook-worker apps/worker
docker run --env-file .env -v models:/models yearbook-worker run --kinds ingest,import
docker run --env-file .env -v models:/models yearbook-worker run --kinds analyze,cluster_event --concurrency 1
docker run --env-file .env -v models:/models -p 8090:8090 yearbook-worker serve --port 8090
```

Models are downloaded at runtime into the `/models` volume (shared by the ML worker and the ML
server), never baked into the image.
