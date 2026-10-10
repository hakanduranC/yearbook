# Build in the official Go image, run from distroless (no shell, non-root).
# Build context must be the repository root: `docker build -f apps/api/Dockerfile .`
# because the migrations live in infra/migrations and ybctl applies them from a directory.
FROM golang:1.27 AS build
WORKDIR /src
COPY apps/api/go.mod apps/api/go.sum ./apps/api/
RUN --mount=type=cache,target=/go/pkg/mod cd apps/api && go mod download
COPY apps/api ./apps/api
COPY infra/migrations ./infra/migrations
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    cd apps/api && CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/api ./cmd/api \
    && CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/ybctl ./cmd/ybctl

FROM gcr.io/distroless/static:nonroot
WORKDIR /app
COPY --from=build /out/api /out/ybctl /app/
COPY --from=build /src/infra/migrations /app/infra/migrations
ENV API_ADDR=:8080
EXPOSE 8080
USER nonroot:nonroot
ENTRYPOINT ["/app/api"]
