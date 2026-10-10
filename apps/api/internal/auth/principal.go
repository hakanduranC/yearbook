// Package auth holds the identity rules: who the caller is (Principal), session and magic-link
// tokens, and the per-email / per-IP rate limits for magic links.
package auth

import (
	"context"

	db "yearbook/api/internal/gen/db"
)

// Principal is the caller as seen by every handler. Both parts may be empty (anonymous).
type Principal struct {
	// User is set when a valid yb_session cookie was presented.
	User *db.User
	// CookieID is the guest_cookies.id from a valid yb_guest cookie, or nil.
	CookieID []byte
	// Share is the (unexpired) share link named by ?share=<id>, the third principal kind. It only
	// widens read access to the shared album's items; it never identifies the caller.
	Share *db.Share
	// IP is the client address after the RealIP middleware.
	IP string
}

// UserID returns the user id or nil.
func (p Principal) UserID() []byte {
	if p.User == nil {
		return nil
	}
	return p.User.ID
}

// Actor is the identity used for likes: the user id when signed in, else the guest cookie id.
func (p Principal) Actor() []byte {
	if p.User != nil {
		return p.User.ID
	}
	return p.CookieID
}

// Anonymous reports whether the caller has neither a session nor a guest cookie.
func (p Principal) Anonymous() bool { return p.User == nil && p.CookieID == nil }

type ctxKey struct{}

// WithPrincipal stores the principal in the context (done by the Principal middleware).
func WithPrincipal(ctx context.Context, p Principal) context.Context {
	return context.WithValue(ctx, ctxKey{}, p)
}

// FromContext returns the principal stored by the middleware, or an anonymous one.
func FromContext(ctx context.Context) Principal {
	p, _ := ctx.Value(ctxKey{}).(Principal)
	return p
}
