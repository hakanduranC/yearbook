// Package db opens the pgx connection pool and runs migrations for ybctl and tests.
package db

import (
	"context"
	"database/sql"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
)

// Connect opens a pool and pings it once so misconfiguration fails at startup.
// timestamptz values are scanned in UTC so JSON timestamps are UTC regardless of the host zone.
func Connect(ctx context.Context, url string) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, fmt.Errorf("db: %w", err)
	}
	cfg.AfterConnect = func(_ context.Context, conn *pgx.Conn) error {
		conn.TypeMap().RegisterType(&pgtype.Type{
			Name: "timestamptz", OID: pgtype.TimestamptzOID, Codec: &pgtype.TimestamptzCodec{ScanLocation: time.UTC},
		})
		return nil
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("db: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("db: ping: %w", err)
	}
	return pool, nil
}

// Migrate applies all goose migrations from dir (a path to infra/migrations).
func Migrate(ctx context.Context, url, dir string) error {
	sqldb, err := sql.Open("pgx", url)
	if err != nil {
		return err
	}
	defer sqldb.Close()
	// stdlib is imported so database/sql knows the "pgx" driver.
	_ = stdlib.GetDefaultDriver
	goose.SetLogger(goose.NopLogger())
	if err := goose.SetDialect("postgres"); err != nil {
		return err
	}
	return goose.UpContext(ctx, sqldb, dir)
}

// MigrationsDir walks up from the working directory until it finds infra/migrations.
// The migrations live at the repo root, outside this Go module, so they cannot be embedded.
func MigrationsDir() (string, error) {
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		candidate := filepath.Join(dir, "infra", "migrations")
		if st, err := os.Stat(candidate); err == nil && st.IsDir() {
			return candidate, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", fmt.Errorf("db: infra/migrations not found above %s", dir)
		}
		dir = parent
	}
}

// AgentLoginRole is the login role the agent's run_query pool connects as; it is a member of the
// nologin role agent_ro that migration 00008 grants the v_* views to.
const AgentLoginRole = "agent_ro_login"

// EnsureAgentRole creates AgentLoginRole (or resets its password) so run_query can connect with
// AGENT_DB_PASSWORD. Roles are cluster-wide; the view grants are per database (migration 00008).
func EnsureAgentRole(ctx context.Context, pool *pgxpool.Pool, password string) error {
	var exists bool
	if err := pool.QueryRow(ctx, "select exists(select 1 from pg_roles where rolname = $1)", AgentLoginRole).Scan(&exists); err != nil {
		return fmt.Errorf("db: agent role: %w", err)
	}
	quoted := quoteLiteral(password)
	stmt := "create role " + AgentLoginRole + " login in role agent_ro password " + quoted
	if exists {
		stmt = "alter role " + AgentLoginRole + " login password " + quoted
	}
	if _, err := pool.Exec(ctx, stmt); err != nil {
		return fmt.Errorf("db: agent role: %w", err)
	}
	if exists {
		if _, err := pool.Exec(ctx, "grant agent_ro to "+AgentLoginRole); err != nil {
			return fmt.Errorf("db: agent role grant: %w", err)
		}
	}
	return nil
}

// AgentURL swaps the credentials of databaseURL for the agent login role (unless agentURL is set).
func AgentURL(databaseURL, agentURL, password string) (string, error) {
	if agentURL != "" {
		return agentURL, nil
	}
	u, err := url.Parse(databaseURL)
	if err != nil {
		return "", fmt.Errorf("db: agent url: %w", err)
	}
	u.User = url.UserPassword(AgentLoginRole, password)
	return u.String(), nil
}

// quoteLiteral quotes s as a Postgres string literal (role passwords cannot be bind parameters).
func quoteLiteral(s string) string {
	return "'" + strings.ReplaceAll(s, "'", "''") + "'"
}
