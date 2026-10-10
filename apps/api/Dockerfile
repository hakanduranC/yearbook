# Build in the official Go image, run from distroless (no shell, non-root).
# Build context must be the repository root: `docker build -f apps/api/Dockerfile .`
# because the migrations live in infra/migrations and ybctl applies them from a directory.
FROM golang:1.27 AS build
# GOPROXY=direct bypasses the module CDN on networks where storage.googleapis.com is unreachable.
ARG GOPROXY=https://proxy.golang.org,direct
ENV GOPROXY=$GOPROXY
WORKDIR /src
COPY apps/api/go.mod apps/api/go.sum ./apps/api/
RUN --mount=type=cache,target=/go/pkg/mod cd apps/api && go mod download
COPY apps/api ./apps/api
COPY infra/migrations ./infra/migrations
# cgo is required: pg_query_go (the SQL guard of the agent tools) links the real Postgres parser.
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    cd apps/api && CGO_ENABLED=1 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/api ./cmd/api \
    && CGO_ENABLED=1 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/ybctl ./cmd/ybctl

FROM gcr.io/distroless/base-debian12:nonroot
WORKDIR /app
COPY --from=build /out/api /out/ybctl /app/
COPY --from=build /src/infra/migrations /app/infra/migrations
ENV API_ADDR=:8080
EXPOSE 8080
USER nonroot:nonroot
ENTRYPOINT ["/app/api"]
