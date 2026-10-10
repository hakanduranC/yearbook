# Yearbook

A shared photo album that assembles itself. Scan a QR at the event, upload from your phone browser, find the photos you are in.

- Design: `docs/SDD.md` (diagrams regenerate with `uv run docs/diagrams/build.py`)
- Conventions every app follows: `docs/CONVENTIONS.md`
- Contract: `packages/openapi/openapi.yaml`

## Run it locally

```
mise install                 # Go, Node, Python, sqlc, goose, air (once)
cp .env.example .env
mise run up                  # Postgres + pgvector, SeaweedFS (S3), Mailpit
mise run migrate
mise run gen                 # generated Go and TS from the contract
mise run api                 # http://localhost:8080
mise run worker
mise run web                 # http://localhost:3000
mise run seed                # demo event with fixture photos; prints a sign-in link
```

Mailpit (magic links in dev): http://localhost:8025 · S3 console: none, use the AWS CLI against http://localhost:8333.
