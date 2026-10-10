package auth

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
)

// Cookie names shared by the API and the web app.
const (
	SessionCookie = "yb_session"
	GuestCookie   = "yb_guest"
)

// Lifetimes from docs/CONVENTIONS.md.
const (
	SessionTTL   = 90 * 24 * time.Hour
	GuestTTL     = 365 * 24 * time.Hour
	MagicLinkTTL = 15 * time.Minute
)

// ErrInvalidToken means the magic link token is unknown, used or expired.
var ErrInvalidToken = errors.New("auth: invalid or expired token")

// newToken returns 32 random bytes as base64url (43 characters) and their sha256 for storage.
func newToken() (token string, hash []byte) {
	raw := make([]byte, 32)
	rand.Read(raw)
	token = base64.RawURLEncoding.EncodeToString(raw)
	return token, hashToken(token)
}

func hashToken(token string) []byte {
	sum := sha256.Sum256([]byte(token))
	return sum[:]
}

// CreateMagicLink stores a fresh token for email and returns the URL the user should open.
func CreateMagicLink(ctx context.Context, q *db.Queries, webOrigin, email, next string) (string, error) {
	token, hash := newToken()
	if next == "" || !strings.HasPrefix(next, "/") || strings.HasPrefix(next, "//") {
		next = "/"
	}
	err := q.CreateMagicLink(ctx, db.CreateMagicLinkParams{
		TokenHash: hash,
		Email:     strings.ToLower(strings.TrimSpace(email)),
		NextPath:  next,
		ExpiresAt: time.Now().Add(MagicLinkTTL),
	})
	if err != nil {
		return "", err
	}
	v := url.Values{"token": {token}, "next": {next}}
	return strings.TrimRight(webOrigin, "/") + "/auth/verify?" + v.Encode(), nil
}

// VerifyMagicLink consumes the token and returns (creating if needed) the user and the next path.
func VerifyMagicLink(ctx context.Context, q *db.Queries, token string) (db.User, string, error) {
	link, err := q.ConsumeMagicLink(ctx, hashToken(token))
	if errors.Is(err, pgx.ErrNoRows) {
		return db.User{}, "", ErrInvalidToken
	}
	if err != nil {
		return db.User{}, "", err
	}
	user, err := q.GetUserByEmail(ctx, link.Email)
	if errors.Is(err, pgx.ErrNoRows) {
		user, err = q.CreateUser(ctx, db.CreateUserParams{
			ID:          ids.New(),
			Email:       link.Email,
			DisplayName: displayNameFromEmail(link.Email),
			Locale:      "de",
		})
	}
	if err != nil {
		return db.User{}, "", err
	}
	return user, link.NextPath, nil
}

// displayNameFromEmail turns "anna.schmidt@example.org" into "Anna Schmidt".
func displayNameFromEmail(email string) string {
	local, _, _ := strings.Cut(email, "@")
	local = strings.NewReplacer(".", " ", "_", " ", "-", " ", "+", " ").Replace(local)
	words := strings.Fields(local)
	for i, w := range words {
		words[i] = strings.ToUpper(w[:1]) + w[1:]
	}
	if len(words) == 0 {
		return "Guest"
	}
	return strings.Join(words, " ")
}

// CreateSession stores a new session for the user and returns the raw cookie value.
func CreateSession(ctx context.Context, q *db.Queries, userID []byte) (string, error) {
	token, hash := newToken()
	err := q.CreateSession(ctx, db.CreateSessionParams{
		TokenHash: hash,
		UserID:    userID,
		ExpiresAt: time.Now().Add(SessionTTL),
	})
	return token, err
}

// LookupSession resolves a cookie value to its user. ok is false for unknown or expired sessions.
// stale reports that the row has not been touched for an hour and should be slid forward.
func LookupSession(ctx context.Context, q *db.Queries, token string) (user db.User, stale bool, ok bool, err error) {
	row, err := q.GetSessionUser(ctx, hashToken(token))
	if errors.Is(err, pgx.ErrNoRows) {
		return db.User{}, false, false, nil
	}
	if err != nil {
		return db.User{}, false, false, err
	}
	user = db.User{ID: row.ID, Email: row.Email, DisplayName: row.DisplayName, Birthdate: row.Birthdate, Locale: row.Locale, CreatedAt: row.CreatedAt}
	return user, time.Since(row.SessionLastSeenAt) > time.Hour, true, nil
}

// TouchSession slides the expiry of a session (called at most once an hour per session).
func TouchSession(ctx context.Context, q *db.Queries, token string) error {
	return q.TouchSession(ctx, hashToken(token))
}

// DeleteSession ends a session; unknown tokens are not an error.
func DeleteSession(ctx context.Context, q *db.Queries, token string) error {
	return q.DeleteSession(ctx, hashToken(token))
}

// SessionCookieFor builds the yb_session cookie. An empty value clears it.
func SessionCookieFor(value string, secure bool) *http.Cookie {
	c := &http.Cookie{
		Name:     SessionCookie,
		Value:    value,
		Path:     "/",
		HttpOnly: true,
		Secure:   secure,
		SameSite: http.SameSiteLaxMode,
		MaxAge:   int(SessionTTL.Seconds()),
	}
	if value == "" {
		c.MaxAge = -1
	}
	return c
}

// GuestCookieFor builds the yb_guest cookie carrying a guest_cookies.id.
func GuestCookieFor(cookieID []byte, secure bool) *http.Cookie {
	return &http.Cookie{
		Name:     GuestCookie,
		Value:    ids.Encode(cookieID),
		Path:     "/",
		HttpOnly: true,
		Secure:   secure,
		SameSite: http.SameSiteLaxMode,
		MaxAge:   int(GuestTTL.Seconds()),
	}
}
