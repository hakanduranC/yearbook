package handlers

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"strings"
	"time"

	openapi_types "github.com/oapi-codegen/runtime/types"

	"yearbook/api/internal/apperr"
	"yearbook/api/internal/auth"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/mail"
	"yearbook/api/internal/middleware"
)

// RequestMagicLink emails a sign-in link. It always answers 204 for well-formed addresses so the
// endpoint does not reveal which addresses have accounts.
func (s *Server) RequestMagicLink(ctx context.Context, req api.RequestMagicLinkRequestObject) (api.RequestMagicLinkResponseObject, error) {
	if req.Body == nil {
		return nil, apperr.BadRequestf("body required")
	}
	email := strings.ToLower(strings.TrimSpace(string(req.Body.Email)))
	if !strings.Contains(email, "@") || len(email) > 254 {
		return nil, apperr.BadRequestf("invalid email")
	}
	p := auth.FromContext(ctx)
	if !s.Limits.PerIP.Allow(p.IP) || !s.Limits.PerEmail.Allow(email) {
		return nil, apperr.New(apperr.RateLimited, "too many sign-in links requested, try again later")
	}
	next := "/"
	if req.Body.Next != nil {
		next = *req.Body.Next
	}
	link, err := auth.CreateMagicLink(ctx, s.Q, s.Cfg.WebOrigin, email, next)
	if err != nil {
		return nil, err
	}
	if s.Cfg.Dev() {
		slog.InfoContext(ctx, "magic link", "email", email, "url", link)
	}
	// Locale: the request wins (the web app knows the UI language), then the account's setting.
	locale := ""
	if req.Body.Locale != nil {
		locale = string(*req.Body.Locale)
	} else if u, err := s.Q.GetUserByEmail(ctx, email); err == nil {
		locale = u.Locale
	}
	if err := s.Mailer.Send(ctx, email, mail.MagicLinkSubject(locale), mail.MagicLinkText(locale, link)); err != nil {
		return nil, err
	}
	return api.RequestMagicLink204Response{}, nil
}

// VerifyMagicLink consumes a token, creates the user on first sign-in and sets yb_session.
func (s *Server) VerifyMagicLink(ctx context.Context, req api.VerifyMagicLinkRequestObject) (api.VerifyMagicLinkResponseObject, error) {
	if req.Body == nil || req.Body.Token == "" {
		return nil, apperr.BadRequestf("token required")
	}
	user, next, err := auth.VerifyMagicLink(ctx, s.Q, req.Body.Token)
	if errors.Is(err, auth.ErrInvalidToken) {
		return nil, apperr.BadRequestf("this link is invalid or has expired")
	}
	if err != nil {
		return nil, err
	}
	token, err := auth.CreateSession(ctx, s.Q, user.ID)
	if err != nil {
		return nil, err
	}
	// Tie an existing guest cookie to the account so earlier guest uploads count as theirs.
	if p := auth.FromContext(ctx); p.CookieID != nil {
		logErr(ctx, "link guest cookie", s.Q.LinkGuestCookieUser(ctx, db.LinkGuestCookieUserParams{ID: p.CookieID, UserID: user.ID}))
	}
	me, err := s.meJSON(ctx, &user)
	if err != nil {
		return nil, err
	}
	return verifyResponse{
		body:   api.VerifyResponse{Next: next, Me: me},
		cookie: auth.SessionCookieFor(token, s.Cfg.CookieSecure),
	}, nil
}

// verifyResponse is a 200 VerifyResponse that also sets the session cookie.
type verifyResponse struct {
	body   api.VerifyResponse
	cookie *http.Cookie
}

func (r verifyResponse) VisitVerifyMagicLinkResponse(w http.ResponseWriter) error {
	http.SetCookie(w, r.cookie)
	return api.VerifyMagicLink200JSONResponse(r.body).VisitVerifyMagicLinkResponse(w)
}

// Logout deletes the session row and clears the cookie.
func (s *Server) Logout(ctx context.Context, _ api.LogoutRequestObject) (api.LogoutResponseObject, error) {
	if r := middleware.RequestFrom(ctx); r != nil {
		if c, err := r.Cookie(auth.SessionCookie); err == nil && c.Value != "" {
			if err := auth.DeleteSession(ctx, s.Q, c.Value); err != nil {
				return nil, err
			}
		}
	}
	return logoutResponse{cookie: auth.SessionCookieFor("", s.Cfg.CookieSecure)}, nil
}

type logoutResponse struct{ cookie *http.Cookie }

func (r logoutResponse) VisitLogoutResponse(w http.ResponseWriter) error {
	http.SetCookie(w, r.cookie)
	w.WriteHeader(http.StatusNoContent)
	return nil
}

// GetMe describes the caller; anonymous callers get authenticated=false.
func (s *Server) GetMe(ctx context.Context, _ api.GetMeRequestObject) (api.GetMeResponseObject, error) {
	me, err := s.meJSON(ctx, auth.FromContext(ctx).User)
	if err != nil {
		return nil, err
	}
	return api.GetMe200JSONResponse(me), nil
}

// meJSON adds the identity-level switches (link_across, hide_from_people, has_claimed_person).
func (s *Server) meJSON(ctx context.Context, u *db.User) (api.Me, error) {
	me := meFor(u)
	if u == nil {
		return me, nil
	}
	identity, err := s.identityFor(ctx, auth.Principal{User: u})
	if err != nil {
		return me, err
	}
	linkAcross, hide, claimed := true, false, false
	if identity != nil {
		linkAcross, hide = identity.LinkAcross, identity.HideFromPeople
		claimed, err = s.Q.IdentityHasClaim(ctx, identity.ID)
		if err != nil {
			return me, err
		}
	}
	me.LinkAcross, me.HideFromPeople, me.HasClaimedPerson = &linkAcross, &hide, &claimed
	return me, nil
}

// UpdateMe changes display name, locale or birthdate.
func (s *Server) UpdateMe(ctx context.Context, req api.UpdateMeRequestObject) (api.UpdateMeResponseObject, error) {
	user, err := requireUser(ctx)
	if err != nil {
		return nil, err
	}
	if req.Body == nil {
		return nil, apperr.BadRequestf("body required")
	}
	params := db.UpdateUserParams{ID: user.ID}
	if req.Body.DisplayName != nil {
		name := strings.TrimSpace(*req.Body.DisplayName)
		if name == "" || len(name) > 80 {
			return nil, apperr.BadRequestf("display_name must be 1 to 80 characters")
		}
		params.DisplayName = &name
	}
	if req.Body.Locale != nil {
		loc := string(*req.Body.Locale)
		if !mail.Locales[loc] {
			return nil, apperr.BadRequestf("locale must be de, en or tr")
		}
		params.Locale = &loc
	}
	if req.Body.ClearBirthdate != nil && *req.Body.ClearBirthdate {
		params.SetBirthdate = true
		params.Birthdate = nil
	} else if req.Body.Birthdate != nil {
		t := req.Body.Birthdate.Time
		if t.After(time.Now()) {
			return nil, apperr.BadRequestf("birthdate must be in the past")
		}
		params.SetBirthdate = true
		params.Birthdate = &t
	}
	updated, err := s.Q.UpdateUser(ctx, params)
	if err != nil {
		return nil, err
	}
	// The identity row mirrors name and birthdate and owns the privacy switches. It is created on
	// demand when a switch is set; otherwise it appears with the first claim.
	identity, err := s.identityFor(ctx, auth.Principal{User: &updated})
	if err != nil {
		return nil, err
	}
	if identity == nil && (req.Body.LinkAcross != nil || req.Body.HideFromPeople != nil) {
		created, err := s.Q.CreateIdentity(ctx, db.CreateIdentityParams{ID: ids.New(), UserID: updated.ID, DisplayName: updated.DisplayName, Birthdate: updated.Birthdate})
		if err != nil {
			return nil, err
		}
		identity = &created
	}
	if identity != nil {
		err := s.Q.UpdateIdentitySettings(ctx, db.UpdateIdentitySettingsParams{
			ID: identity.ID, DisplayName: params.DisplayName, SetBirthdate: params.SetBirthdate, Birthdate: params.Birthdate,
			LinkAcross: req.Body.LinkAcross, HideFromPeople: req.Body.HideFromPeople,
		})
		if err != nil {
			return nil, err
		}
	}
	me, err := s.meJSON(ctx, &updated)
	if err != nil {
		return nil, err
	}
	return api.UpdateMe200JSONResponse(me), nil
}

// meFor shapes a user (or nil for anonymous) as Me.
func meFor(u *db.User) api.Me {
	if u == nil {
		return api.Me{Authenticated: false, Locale: api.MeLocale("de")}
	}
	id := ids.Encode(u.ID)
	me := api.Me{
		Authenticated: true,
		Id:            &id,
		Email:         &u.Email,
		DisplayName:   &u.DisplayName,
		Locale:        api.MeLocale(u.Locale),
	}
	if u.Birthdate != nil {
		me.Birthdate = &openapi_types.Date{Time: *u.Birthdate}
	}
	return me
}
