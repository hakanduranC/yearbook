// Package handlers implements the generated StrictServerInterface. Handlers stay thin: they
// parse, authorise, call a query or a package, and shape the response. Rules live in
// internal/auth, internal/media, internal/storage and internal/realtime.
package handlers

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"yearbook/api/internal/apperr"
	"yearbook/api/internal/auth"
	"yearbook/api/internal/config"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/mail"
	"yearbook/api/internal/realtime"
	"yearbook/api/internal/storage"
)

// Server holds the dependencies every handler needs. It implements api.StrictServerInterface.
type Server struct {
	Cfg     config.Config
	Pool    *pgxpool.Pool
	Q       *db.Queries
	Store   *storage.Client
	Hub     *realtime.Hub
	Mailer  mail.Sender
	Limits  auth.MagicLinkLimits
	Version string

	zips *zipTickets
}

// New wires a Server. The caller owns the pool and the hub.
func New(cfg config.Config, pool *pgxpool.Pool, store *storage.Client, hub *realtime.Hub, mailer mail.Sender, version string) *Server {
	return &Server{
		Cfg:     cfg,
		Pool:    pool,
		Q:       db.New(pool),
		Store:   store,
		Hub:     hub,
		Mailer:  mailer,
		Limits:  auth.NewMagicLinkLimits(),
		Version: version,
		zips:    newZipTickets(10 * time.Minute),
	}
}

var _ api.StrictServerInterface = (*Server)(nil)

// GetHealth answers the liveness probe.
func (s *Server) GetHealth(ctx context.Context, _ api.GetHealthRequestObject) (api.GetHealthResponseObject, error) {
	if err := s.Pool.Ping(ctx); err != nil {
		return nil, err
	}
	return api.GetHealth200JSONResponse{Status: api.Ok, Version: s.Version}, nil
}

// viewer is the caller in relation to one event.
type viewer struct {
	p     auth.Principal
	event db.Event
	role  api.ViewerRole
	guest *db.Guest // the caller's guest row in this event, if any
}

// isHost reports whether the viewer may manage the event.
func (v viewer) isHost() bool { return v.role == api.ViewerRoleOwner || v.role == api.ViewerRoleHost }

// canView reports whether the viewer may see the event's media.
func (v viewer) canView() bool { return v.event.GuestView || v.isHost() }

// guestID is the guests.id of the viewer in this event, or nil.
func (v viewer) guestID() []byte {
	if v.guest == nil {
		return nil
	}
	return v.guest.ID
}

// viewerFor resolves the caller's role in ev: owner, host, member (event_members), guest (a guests
// row for the yb_guest cookie) or anonymous.
func (s *Server) viewerFor(ctx context.Context, ev db.Event) (viewer, error) {
	p := auth.FromContext(ctx)
	v := viewer{p: p, event: ev, role: api.ViewerRoleAnonymous}

	if p.CookieID != nil {
		g, err := s.Q.GetGuest(ctx, db.GetGuestParams{EventID: ev.ID, CookieID: p.CookieID})
		switch {
		case err == nil:
			v.guest = &g
			v.role = api.ViewerRoleGuest
		case !errors.Is(err, pgx.ErrNoRows):
			return v, err
		}
	}
	if p.User != nil {
		switch {
		case string(ev.OwnerID) == string(p.User.ID):
			v.role = api.ViewerRoleOwner
		default:
			role, err := s.Q.GetEventMemberRole(ctx, db.GetEventMemberRoleParams{EventID: ev.ID, UserID: p.User.ID})
			if err == nil {
				v.role = api.ViewerRole(role)
			} else if !errors.Is(err, pgx.ErrNoRows) {
				return v, err
			}
		}
	}
	return v, nil
}

// eventBySlug loads an event or returns a 404 error.
func (s *Server) eventBySlug(ctx context.Context, slug string) (db.GetEventBySlugRow, error) {
	row, err := s.Q.GetEventBySlug(ctx, slug)
	if errors.Is(err, pgx.ErrNoRows) {
		return row, apperr.NotFoundf("event not found")
	}
	return row, err
}

// requireUser returns the signed-in user or a 401 error.
func requireUser(ctx context.Context) (*db.User, error) {
	p := auth.FromContext(ctx)
	if p.User == nil {
		return nil, apperr.Unauthorizedf("")
	}
	return p.User, nil
}

// inTx runs fn inside one transaction with a Queries bound to it.
func (s *Server) inTx(ctx context.Context, fn func(q *db.Queries) error) error {
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx) //nolint:errcheck // rollback after commit is a harmless no-op
	if err := fn(s.Q.WithTx(tx)); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// logErr logs a non-fatal error with the request context (used for best-effort cleanups).
func logErr(ctx context.Context, msg string, err error) {
	if err != nil {
		slog.ErrorContext(ctx, msg, "err", err)
	}
}
