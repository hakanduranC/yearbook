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

	S3Endpoint       string `env:"S3_ENDPOINT,required"`
	S3Region         string `env:"S3_REGION" envDefault:"us-east-1"`
	S3AccessKey      string `env:"S3_ACCESS_KEY,required"`
	S3SecretKey      string `env:"S3_SECRET_KEY,required"`
	S3ForcePathStyle bool   `env:"S3_FORCE_PATH_STYLE" envDefault:"true"`
	S3BucketPrivate  string `env:"S3_BUCKET_PRIVATE,required"`
	S3BucketPublic   string `env:"S3_BUCKET_PUBLIC,required"`
	PublicBaseURL    string `env:"PUBLIC_BASE_URL,required"`

	Addr           string   `env:"API_ADDR" envDefault:":8080"`
	WebOrigin      string   `env:"WEB_ORIGIN" envDefault:"http://localhost:3000"`
	AllowedOrigins []string `env:"ALLOWED_ORIGINS" envSeparator:","`
	CookieSecure   bool     `env:"COOKIE_SECURE" envDefault:"false"`
	SessionSecret  string   `env:"SESSION_SECRET,required"`

	SMTPHost string `env:"SMTP_HOST" envDefault:"localhost"`
	SMTPPort int    `env:"SMTP_PORT" envDefault:"1025"`
	SMTPFrom string `env:"SMTP_FROM" envDefault:"Yearbook <hello@yearbook.local>"`
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
