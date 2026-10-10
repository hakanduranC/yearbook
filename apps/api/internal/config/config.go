// Package config loads the API configuration from the environment (mise loads .env at the repo root).
package config

import (
	"fmt"

	"github.com/caarlos0/env/v11"
)

// Config holds every setting the API reads from the environment.
type Config struct {
	Env string `env:"APP_ENV" envDefault:"dev"` // dev | prod

	DatabaseURL     string `env:"DATABASE_URL,required"`
	TestDatabaseURL string `env:"TEST_DATABASE_URL"`

	S3Endpoint string `env:"S3_ENDPOINT,required"`
	// S3PresignEndpoint is the endpoint browsers can reach for presigned URLs. Defaults to S3_ENDPOINT.
	// Needed when the API talks to S3 over an internal network name (Compose, Kubernetes).
	S3PresignEndpoint string `env:"S3_PRESIGN_ENDPOINT"`
	S3Region          string `env:"S3_REGION" envDefault:"us-east-1"`
	S3AccessKey       string `env:"S3_ACCESS_KEY,required"`
	S3SecretKey       string `env:"S3_SECRET_KEY,required"`
	S3ForcePathStyle  bool   `env:"S3_FORCE_PATH_STYLE" envDefault:"true"`
	S3BucketPrivate   string `env:"S3_BUCKET_PRIVATE,required"`
	S3BucketPublic    string `env:"S3_BUCKET_PUBLIC,required"`
	PublicBaseURL     string `env:"PUBLIC_BASE_URL,required"`

	Addr           string   `env:"API_ADDR" envDefault:":8080"`
	WebOrigin      string   `env:"WEB_ORIGIN" envDefault:"http://localhost:3000"`
	AllowedOrigins []string `env:"ALLOWED_ORIGINS" envSeparator:","`
	CookieSecure   bool     `env:"COOKIE_SECURE" envDefault:"false"`
	SessionSecret  string   `env:"SESSION_SECRET,required"`

	SMTPHost string `env:"SMTP_HOST" envDefault:"localhost"`
	SMTPPort int    `env:"SMTP_PORT" envDefault:"1025"`
	SMTPFrom string `env:"SMTP_FROM" envDefault:"Yearbook <hello@yearbook.local>"`

	// MLURL is the worker's ML server (text embeddings for search). Unreachable = text-only search.
	MLURL string `env:"ML_URL" envDefault:"http://localhost:8090"`

	// AgentURL is the Python LangGraph service (apps/agent) that runs the language-model loop.
	// POST /agent/messages, POST /agent/commands and POST /media/{id}/describe proxy to it; when
	// it is unreachable they answer 503 agent_not_configured.
	AgentURL string `env:"AGENT_URL" envDefault:"http://localhost:8091"`
	// AgentDBURL connects run_query as the read-only role. Empty = DATABASE_URL with the
	// credentials swapped for agent_ro_login (the login role `ybctl migrate` creates inside
	// agent_ro) and AGENT_DB_PASSWORD.
	AgentDBURL      string `env:"AGENT_DB_URL"`
	AgentDBPassword string `env:"AGENT_DB_PASSWORD" envDefault:"agent-ro-dev"`

	// OperatorEmail may start folder imports from a server path (POST /imports kind=folder with path).
	OperatorEmail string `env:"OPERATOR_EMAIL"`
}

// Load reads the environment and validates the few invariants that are not expressible as tags.
func Load() (Config, error) {
	var c Config
	if err := env.Parse(&c); err != nil {
		return c, fmt.Errorf("config: %w", err)
	}
	if len(c.AllowedOrigins) == 0 {
		c.AllowedOrigins = []string{c.WebOrigin}
	}
	if len(c.SessionSecret) < 32 {
		return c, fmt.Errorf("config: SESSION_SECRET must be at least 32 bytes")
	}
	return c, nil
}

// Dev reports whether the API runs in development mode (extra logging such as magic links).
func (c Config) Dev() bool { return c.Env != "prod" }
