package middleware

import (
	"net/http"
	"slices"
	"strings"

	"yearbook/api/internal/apperr"
)

// CORS answers cross-origin requests only for origins in allowed and only when the request
// really is cross-origin (Origin differs from the request host). Same-origin calls through the
// Vite proxy or Caddy never see these headers.
func CORS(allowed []string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			origin := r.Header.Get("Origin")
			if origin == "" || sameOrigin(r, origin) || !slices.Contains(allowed, origin) {
				next.ServeHTTP(w, r)
				return
			}
			h := w.Header()
			h.Set("Access-Control-Allow-Origin", origin)
			h.Set("Access-Control-Allow-Credentials", "true")
			h.Add("Vary", "Origin")
			if r.Method == http.MethodOptions && r.Header.Get("Access-Control-Request-Method") != "" {
				h.Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
				h.Set("Access-Control-Allow-Headers", "Content-Type, Last-Event-ID")
				h.Set("Access-Control-Max-Age", "600")
				w.WriteHeader(http.StatusNoContent)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// sameOrigin reports whether origin names this server (scheme and host).
func sameOrigin(r *http.Request, origin string) bool {
	scheme := "http"
	if r.TLS != nil || strings.EqualFold(r.Header.Get("X-Forwarded-Proto"), "https") {
		scheme = "https"
	}
	return strings.EqualFold(origin, scheme+"://"+r.Host)
}

// CSRF rejects cookie-authenticated mutations that do not come from an allowed origin.
// A browser always sends Origin on POST/PUT/PATCH/DELETE; same-origin fetches through a proxy
// carry Sec-Fetch-Site: same-origin instead.
func CSRF(allowed []string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			switch r.Method {
			case http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete:
				origin := r.Header.Get("Origin")
				ok := (origin != "" && (slices.Contains(allowed, origin) || sameOrigin(r, origin))) ||
					r.Header.Get("Sec-Fetch-Site") == "same-origin"
				if !ok {
					apperr.Write(w, r, apperr.Forbiddenf("origin not allowed"))
					return
				}
			}
			next.ServeHTTP(w, r)
		})
	}
}
