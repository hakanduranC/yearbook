// Command api runs the Yearbook HTTP API.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"runtime/debug"
	"syscall"
	"time"

	"yearbook/api/internal/config"
	"yearbook/api/internal/db"
	"yearbook/api/internal/handlers"
	"yearbook/api/internal/httpserver"
	"yearbook/api/internal/mail"
	"yearbook/api/internal/realtime"
	"yearbook/api/internal/search"
	"yearbook/api/internal/storage"
)

func main() {
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))
	if err := run(); err != nil {
		slog.Error("api exited", "err", err)
		os.Exit(1)
	}
}

func run() error {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	cfg, err := config.Load()
	if err != nil {
		return err
	}
	pool, err := db.Connect(ctx, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	defer pool.Close()
	store, err := storage.New(ctx, cfg)
	if err != nil {
		return err
	}
	hub := realtime.NewHub()
	mailer := mail.SMTP{Host: cfg.SMTPHost, Port: cfg.SMTPPort, From: cfg.SMTPFrom}
	deps := handlers.Deps{Pool: pool, Store: store, Hub: hub, Mailer: mailer, Version: version(), Embedder: search.NewHTTPEmbedder(cfg.MLURL)}
	// run_query connects as the read-only agent role on its own small pool; without it the tool
	// reports itself unavailable instead of failing the whole API.
	if agentURL, err := db.AgentURL(cfg.DatabaseURL, cfg.AgentDBURL, cfg.AgentDBPassword); err == nil {
		if agentPool, err := db.Connect(ctx, agentURL); err != nil {
			slog.Warn("agent: read-only pool unavailable, run_query disabled (run `ybctl migrate` to create the role)", "err", err)
		} else {
			defer agentPool.Close()
			deps.AgentPool = agentPool
		}
	}
	slog.Info("agent service", "url", cfg.AgentURL, "ml_url", cfg.MLURL)
	srv := handlers.New(cfg, deps)

	go realtime.Listen(ctx, cfg.DatabaseURL, hub, srv.TranslateNotification)

	httpSrv := &http.Server{
		Addr:              cfg.Addr,
		Handler:           httpserver.New(cfg, srv),
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       120 * time.Second,
	}
	errCh := make(chan error, 1)
	go func() {
		slog.Info("api listening", "addr", cfg.Addr, "env", cfg.Env)
		errCh <- httpSrv.ListenAndServe()
	}()

	select {
	case err := <-errCh:
		if !errors.Is(err, http.ErrServerClosed) {
			return err
		}
	case <-ctx.Done():
		slog.Info("shutting down")
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		return httpSrv.Shutdown(shutdownCtx)
	}
	return nil
}

// version is the VCS revision baked in by `go build`, or "dev".
func version() string {
	if info, ok := debug.ReadBuildInfo(); ok {
		for _, s := range info.Settings {
			if s.Key == "vcs.revision" && len(s.Value) >= 8 {
				return s.Value[:8]
			}
		}
	}
	return "dev"
}
