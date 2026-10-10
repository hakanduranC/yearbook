// Package httpserver assembles the router: chi middleware chain, generated routes and error mapping.
package httpserver

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"runtime/debug"
	"strconv"
	"sync"

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
	r.Use(chimw.Compress(5, "application/json", "image/svg+xml", "text/plain", "text/html"))
	r.Use(middleware.CORS(cfg.AllowedOrigins))
	r.Use(middleware.WithRequest)
	r.Use(middleware.Principal(srv.Q, cfg.CookieSecure))

	// The contract, behind the CSRF origin check for mutations (browser cookies).
	r.Group(func(g chi.Router) {
		g.Use(middleware.CSRF(cfg.AllowedOrigins))
		strict := api.NewStrictHandlerWithOptions(srv, nil, api.StrictHTTPServerOptions{
			RequestErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
				apperr.Write(w, r, apperr.BadRequestf(err.Error()))
			},
			ResponseErrorHandlerFunc: apperr.Write,
		})
		api.HandlerWithOptions(strict, api.ChiServerOptions{
			BaseURL:    BasePath,
			BaseRouter: g,
			ErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
				apperr.Write(w, r, apperr.BadRequestf(err.Error()))
			},
		})
	})

	// Spec and Swagger UI, unauthenticated. "Try it out" runs same-origin, so cookies apply.
	r.Get(BasePath+"/openapi.json", serveSpec)
	r.Get("/api/docs", serveDocs)

	// MCP: bearer-authenticated JSON-RPC from the agent service, not a browser, so no CSRF check.
	r.Handle("/mcp", srv.MCPHandler())

	r.NotFound(func(w http.ResponseWriter, r *http.Request) {
		apperr.Write(w, r, apperr.NotFoundf("no such route"))
	})
	r.MethodNotAllowed(func(w http.ResponseWriter, r *http.Request) {
		apperr.Write(w, r, apperr.New(apperr.BadRequest, "method not allowed"))
	})
	return r
}

// specJSON renders the embedded contract once.
var specJSON = sync.OnceValues(func() ([]byte, error) {
	spec, err := api.GetSpec()
	if err != nil {
		return nil, err
	}
	return json.Marshal(spec)
})

func serveSpec(w http.ResponseWriter, r *http.Request) {
	data, err := specJSON()
	if err != nil {
		apperr.Write(w, r, err)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "public, max-age=300")
	w.Header().Set("Content-Length", strconv.Itoa(len(data)))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(data)
}

// SwaggerUIVersion is the pinned swagger-ui-dist release loaded from cdnjs.
const SwaggerUIVersion = "5.17.14"

const docsHTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yearbook API</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/` + SwaggerUIVersion + `/swagger-ui.min.css">
<style>body{margin:0;background:#fff}.topbar{display:none}</style>
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/` + SwaggerUIVersion + `/swagger-ui-bundle.min.js" crossorigin="anonymous"></script>
<script>
window.ui = SwaggerUIBundle({
  url: "` + BasePath + `/openapi.json",
  dom_id: "#swagger-ui",
  deepLinking: true,
  withCredentials: true,
  requestInterceptor: function (req) { req.credentials = "include"; return req; },
  persistAuthorization: true
});
</script>
</body>
</html>
`

func serveDocs(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "public, max-age=300")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(docsHTML))
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
