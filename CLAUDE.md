# Yearbook

Shared photo album that assembles itself: QR at the event, guests upload from the phone browser, faces are grouped so people find themselves, a chat agent answers "photos of me and Anna". A multi-tenant product for many families; piloted on one VPS first, public launch items are SDD milestone M7.

## Read first

- `docs/SDD.md` is the single design document: requirements, flows, architecture, data model, sequences, pipeline, agent, wireframes, privacy, plan. Keep it the only prose doc; do not add parallel markdown files.
- Diagrams are generated: edit `docs/diagrams/build.py`, run `uv run docs/diagrams/build.py`, commit the PNG/SVG. Never hand-edit images or add Mermaid.
- Visual design lives in Claude Design, canvas "Yearbook core screens", rows Final and Final · host and account screens. Token values in its `final.css` win over the design system's `tokens.json` until that file is reconciled.

## Stack (decided, don't relitigate without a reason)

| Part | Choice |
|---|---|
| Web | TanStack Start on Vite, React 19, TanStack Router + Query, TypeScript 5.9 strict, CSS Modules with token variables, fonts self-hosted via Fontsource. No Next.js, no Tailwind |
| API | Go 1.23+, chi, sqlc, pgx, goose migrations, `oapi-codegen` from `packages/openapi/openapi.yaml`; SSE for live updates; MCP server at `/mcp` |
| Workers | Python 3.12 with uv; ONNX Runtime; InsightFace antelopev2, SigLIP 2 so400m, aesthetic-predictor-v2.5, Florence-2, MiVOLO v2, ffmpeg |
| Data | PostgreSQL 16 + pgvector (HNSW, cosine), full-text + pg_trgm; Postgres table as job queue (`SKIP LOCKED`) |
| Storage | Cloudflare R2 or Hetzner Object Storage behind a CDN; SeaweedFS in dev (MinIO is discontinued). Originals and crops private, variants public under random keys. Yearbook is the destination: Google Takeout / folder import, Picker and share-target doors; no live aggregation of Google or iCloud libraries (no APIs for it) |
| LLM | OpenAI Responses API through a LangGraph service (`apps/agent`, Python, langchain-openai, langchain-mcp-adapters, Postgres checkpointer). Not the Claude API. The Go API owns the tools and exposes them over MCP; the agent service only orchestrates. Text and metadata only; pixels and embeddings never leave the server |
| Deploy | Pilot: Docker Compose on one Hetzner VPS, Caddy for TLS. Target: Kubernetes with Ingress. EU only |

## Planned layout

```
apps/web  apps/api  apps/worker  apps/agent  packages/openapi  infra/{compose.yaml,caddy,migrations}  docs/
```

## Conventions

- The OpenAPI file is the contract. Change it first, regenerate Go stubs and the TS client, then implement.
- `media.event_id` is nullable and `media.owner_id` identifies the library owner: personal library next to events.
- Public ids are 16 random bytes; event slugs are readable + random suffix and act as capabilities.
- UI copy: sentence case, short verbs, address the reader as "you", German and English together, no emoji. Gold (`#9a7645`) is reserved for anything about the viewer.
- Privacy is a design constraint: no face crop, embedding, birthdate, email or GPS value may be sent to any third-party API or exposed through the agent's SQL views.
- Prefer one SQL statement over N round trips; hybrid search is a single query.
- Tests: Go integration tests against Postgres in Compose, pytest on the 50-photo fixture set in `apps/worker/fixtures`, Playwright on the guest upload path.

## Owner preferences

Fluent in Python, learning Go on this project (explain idioms briefly when they matter). Prefers few, maintained documents over many. Dislikes Markdown diagrams; use the Python build script.
