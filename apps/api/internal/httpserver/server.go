// Package httpserver assembles the router: chi middleware chain, generated routes and error mapping.
package httpserver

import (
	"log/slog"
	"net/http"
	"runtime/debug"

	"github.com/go-chi/chi/v5"
	chimw "github.com/go-chi/chi/v5/middleware"

	"yearbook/api/internal/apperr"
	"yearbook/api/internal/config"
	api "yearbook/api/internal/gen/api"
	"yearbook/api/internal/handlers"
	"yearbook/api/internal/middleware"
)

// BasePath is where the contract mounts (servers.url in openapi.yaml).
const BasePath = "/api/v1"

// New builds the http.Handler for the API.
func New(cfg config.Config, srv *handlers.Server) http.Handler {
	r := chi.NewRouter()
	r.Use(chimw.RequestID)
	r.Use(chimw.RealIP)
	r.Use(middleware.Logger)
	r.Use(recoverer)
	// chi's compressor only touches the listed content types, so text/event-stream passes through untouched.
	r.Use(chimw.Compress(5, "application/json", "image/svg+xml", "text/plain"))
	r.Use(middleware.CORS(cfg.AllowedOrigins))
	r.Use(middleware.WithRequest)
	r.Use(middleware.Principal(srv.Q, cfg.CookieSecure))
	r.Use(middleware.CSRF(cfg.AllowedOrigins))

	strict := api.NewStrictHandlerWithOptions(srv, nil, api.StrictHTTPServerOptions{
		RequestErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
			apperr.Write(w, r, apperr.BadRequestf(err.Error()))
		},
		ResponseErrorHandlerFunc: apperr.Write,
	})
	api.HandlerWithOptions(strict, api.ChiServerOptions{
		BaseURL:    BasePath,
		BaseRouter: r,
		ErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
			apperr.Write(w, r, apperr.BadRequestf(err.Error()))
		},
	})
	r.NotFound(func(w http.ResponseWriter, r *http.Request) {
		apperr.Write(w, r, apperr.NotFoundf("no such route"))
	})
	r.MethodNotAllowed(func(w http.ResponseWriter, r *http.Request) {
		apperr.Write(w, r, apperr.New(apperr.BadRequest, "method not allowed"))
	})
	return r
}

// recoverer turns panics into a JSON 500 and a logged stack trace.
func recoverer(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil && rec != http.ErrAbortHandler {
				slog.ErrorContext(r.Context(), "panic", "err", rec, "stack", string(debug.Stack()))
				apperr.Write(w, r, apperr.New(apperr.Internal, "internal error"))
			}
		}()
		next.ServeHTTP(w, r)
	})
}
