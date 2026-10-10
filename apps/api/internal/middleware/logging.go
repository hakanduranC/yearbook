// Package middleware contains the HTTP middleware chain: request logging, CORS, CSRF origin checks
// and principal resolution from cookies. Generic pieces (RequestID, RealIP, Recoverer, Compress)
// come from chi.
package middleware

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	chimw "github.com/go-chi/chi/v5/middleware"
)

// Logger writes one slog line per request with method, path, status, bytes and duration.
func Logger(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		ww := chimw.NewWrapResponseWriter(w, r.ProtoMajor)
		next.ServeHTTP(ww, r)
		level := slog.LevelInfo
		if ww.Status() >= 500 {
			level = slog.LevelError
		}
		slog.Log(r.Context(), level, "http",
			"method", r.Method,
			"path", r.URL.Path,
			"status", ww.Status(),
			"bytes", ww.BytesWritten(),
			"ms", time.Since(start).Milliseconds(),
			"ip", r.RemoteAddr,
			"request_id", chimw.GetReqID(r.Context()),
		)
	})
}

type requestKey struct{}

// WithRequest stores the *http.Request in its own context so strict handlers that need a raw
// header (Last-Event-ID) can reach it.
func WithRequest(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := context.WithValue(r.Context(), requestKey{}, r)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// RequestFrom returns the request stored by WithRequest, or nil.
func RequestFrom(ctx context.Context) *http.Request {
	r, _ := ctx.Value(requestKey{}).(*http.Request)
	return r
}
