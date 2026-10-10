package handlers

import (
	"context"
	"errors"
	"net/http"
	"strings"

	"github.com/jackc/pgx/v5"

	"yearbook/api/internal/apperr"
	"yearbook/api/internal/auth"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
)

// EnsureGuest creates the browser's guest cookie (if missing) and its guest row in this event.
// Idempotent: calling it again returns the same guest.
func (s *Server) EnsureGuest(ctx context.Context, req api.EnsureGuestRequestObject) (api.EnsureGuestResponseObject, error) {
	row, err := s.eventBySlug(ctx, req.Slug)
	if err != nil {
		return nil, err
	}
	p := auth.FromContext(ctx)
	cookieID := p.CookieID
	var setCookie *http.Cookie
	if cookieID == nil {
		cookieID = ids.New()
		if err := s.Q.CreateGuestCookie(ctx, db.CreateGuestCookieParams{ID: cookieID, UserID: p.UserID()}); err != nil {
			return nil, err
		}
		setCookie = auth.GuestCookieFor(cookieID, s.Cfg.CookieSecure)
	} else if p.User != nil {
		logErr(ctx, "link guest cookie", s.Q.LinkGuestCookieUser(ctx, db.LinkGuestCookieUserParams{ID: cookieID, UserID: p.User.ID}))
	}
	g, err := s.ensureGuestRow(ctx, row.Event.ID, cookieID)
	if err != nil {
		return nil, err
	}
	return guestResponse{body: guestJSON(g), cookie: setCookie}, nil
}

// ensureGuestRow upserts the guests row for a cookie in an event.
func (s *Server) ensureGuestRow(ctx context.Context, eventID, cookieID []byte) (db.Guest, error) {
	return s.Q.UpsertGuest(ctx, db.UpsertGuestParams{ID: ids.New(), EventID: eventID, CookieID: cookieID})
}

type guestResponse struct {
	body   api.Guest
	cookie *http.Cookie
}

func (r guestResponse) VisitEnsureGuestResponse(w http.ResponseWriter) error {
	if r.cookie != nil {
		http.SetCookie(w, r.cookie)
	}
	return api.EnsureGuest200JSONResponse(r.body).VisitEnsureGuestResponse(w)
}

// UpdateGuest sets the display name guests enter after uploading.
func (s *Server) UpdateGuest(ctx context.Context, req api.UpdateGuestRequestObject) (api.UpdateGuestResponseObject, error) {
	row, err := s.eventBySlug(ctx, req.Slug)
	if err != nil {
		return nil, err
	}
	p := auth.FromContext(ctx)
	if p.CookieID == nil {
		return nil, apperr.Unauthorizedf("no guest identity; call POST /events/{slug}/guests first")
	}
	if req.Body == nil {
		return nil, apperr.BadRequestf("body required")
	}
	name := strings.TrimSpace(req.Body.DisplayName)
	if name == "" || len(name) > 80 {
		return nil, apperr.BadRequestf("display_name must be 1 to 80 characters")
	}
	g, err := s.Q.GetGuest(ctx, db.GetGuestParams{EventID: row.Event.ID, CookieID: p.CookieID})
	if errors.Is(err, pgx.ErrNoRows) {
		g, err = s.ensureGuestRow(ctx, row.Event.ID, p.CookieID)
	}
	if err != nil {
		return nil, err
	}
	g, err = s.Q.UpdateGuestName(ctx, db.UpdateGuestNameParams{ID: g.ID, DisplayName: &name})
	if err != nil {
		return nil, err
	}
	return api.UpdateGuest200JSONResponse(guestJSON(g)), nil
}

func guestJSON(g db.Guest) api.Guest {
	return api.Guest{GuestId: ids.Encode(g.ID), DisplayName: g.DisplayName}
}
