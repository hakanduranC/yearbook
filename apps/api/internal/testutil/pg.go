// Package testutil wires a real Postgres, S3 and the full HTTP handler for integration tests.
// Tests run sequentially inside one package and share TEST_DATABASE_URL; every test starts
// from truncated tables.
package testutil

import (
	"context"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"

	"yearbook/api/internal/config"
	"yearbook/api/internal/db"
	"yearbook/api/internal/handlers"
	"yearbook/api/internal/httpserver"
	"yearbook/api/internal/mail"
	"yearbook/api/internal/realtime"
	"yearbook/api/internal/storage"
)

// App is a running test instance.
type App struct {
	Cfg    config.Config
	Pool   *pgxpool.Pool
	Server *handlers.Server
	Hub    *realtime.Hub
	Mail   *mail.Recorder
	HTTP   *httptest.Server
}

// tables are truncated between tests, children first is not needed thanks to CASCADE.
var tables = []string{
	"likes", "album_items", "albums", "shares", "person_links", "identities", "person_constraints", "faces", "persons",
	"media_embeddings", "media_quality", "media_tags", "media_variants", "duplicate_groups", "media", "jobs",
	"guests", "guest_cookies", "event_members", "events", "magic_links", "sessions", "users",
}

// Start loads config from the environment, migrates and truncates the test database, and serves
// the API on a random port. It skips the test when TEST_DATABASE_URL is not set.
func Start(t *testing.T) *App {
	t.Helper()
	loadDotEnv(t)
	cfg, err := config.Load()
	if err != nil {
		t.Skipf("config: %v", err)
	}
	if cfg.TestDatabaseURL == "" {
		t.Skip("TEST_DATABASE_URL not set")
	}
	cfg.DatabaseURL = cfg.TestDatabaseURL
	cfg.Env = "test"

	ctx := context.Background()
	dir, err := db.MigrationsDir()
	if err != nil {
		t.Fatal(err)
	}
	if err := db.Migrate(ctx, cfg.DatabaseURL, dir); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	pool, err := db.Connect(ctx, cfg.DatabaseURL)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	t.Cleanup(pool.Close)
	for _, tbl := range tables {
		if _, err := pool.Exec(ctx, "truncate table "+tbl+" cascade"); err != nil {
			t.Fatalf("truncate %s: %v", tbl, err)
		}
	}

	store, err := storage.New(ctx, cfg)
	if err != nil {
		t.Fatalf("storage: %v", err)
	}
	hub := realtime.NewHub()
	rec := &mail.Recorder{}
	srv := handlers.New(cfg, pool, store, hub, rec, "test")
	ts := httptest.NewServer(httpserver.New(cfg, srv))
	t.Cleanup(ts.Close)
	return &App{Cfg: cfg, Pool: pool, Server: srv, Hub: hub, Mail: rec, HTTP: ts}
}

// loadDotEnv sets variables from the repo's .env when they are not already in the environment,
// so `go test` works without mise.
func loadDotEnv(t *testing.T) {
	t.Helper()
	_, file, _, _ := runtime.Caller(0)
	dir := filepath.Dir(file)
	for range 6 {
		data, err := os.ReadFile(filepath.Join(dir, ".env"))
		if err == nil {
			applyEnv(string(data))
			return
		}
		dir = filepath.Dir(dir)
	}
}

func applyEnv(data string) {
	for _, line := range strings.Split(data, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok || os.Getenv(key) != "" {
			continue
		}
		value = strings.Trim(strings.TrimSpace(value), `"`)
		os.Setenv(key, value)
	}
}
