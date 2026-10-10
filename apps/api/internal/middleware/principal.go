package middleware

import (
	"log/slog"
	"net"
	"net/http"

	"yearbook/api/internal/auth"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
)

// Principal resolves yb_session and yb_guest into an auth.Principal on the context.
// Invalid cookies are ignored (the caller is simply anonymous); valid sessions slide forward.
func Principal(q *db.Queries, cookieSecure bool) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			ctx := r.Context()
			p := auth.Principal{IP: clientIP(r.RemoteAddr)}

			if c, err := r.Cookie(auth.SessionCookie); err == nil && c.Value != "" {
				user, stale, ok, err := auth.LookupSession(ctx, q, c.Value)
				if err != nil {
					slog.ErrorContext(ctx, "session lookup", "err", err)
				}
				if ok {
					p.User = &user
					if stale {
						if err := auth.TouchSession(ctx, q, c.Value); err == nil {
							http.SetCookie(w, auth.SessionCookieFor(c.Value, cookieSecure))
						}
					}
				}
			}

			if c, err := r.Cookie(auth.GuestCookie); err == nil {
				if id, err := ids.Decode(c.Value); err == nil {
					if exists, err := q.GuestCookieExists(ctx, id); err == nil && exists {
						p.CookieID = id
					}
				}
			}

			// Share links: ?share=<share_id> on media requests from a /s/{share_id} page.
			if sid := r.URL.Query().Get("share"); sid != "" {
				if id, err := ids.Decode(sid); err == nil {
					if sh, err := q.GetShare(ctx, id); err == nil {
						p.Share = &sh
					}
				}
			}

			next.ServeHTTP(w, r.WithContext(auth.WithPrincipal(ctx, p)))
		})
	}
}

func clientIP(remoteAddr string) string {
	if host, _, err := net.SplitHostPort(remoteAddr); err == nil {
		return host
	}
	return remoteAddr
}
