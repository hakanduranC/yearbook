// Package handlers implements the generated StrictServerInterface. Handlers stay thin: they
// parse, authorise, call a query or a package, and shape the response. Rules live in
// internal/auth, internal/media, internal/storage and internal/realtime.
package handlers

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"yearbook/api/internal/agent"
	"yearbook/api/internal/apperr"
	"yearbook/api/internal/auth"
	"yearbook/api/internal/config"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/mail"
	"yearbook/api/internal/realtime"
	"yearbook/api/internal/search"
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

	// Embedder is the ML server's text tower for hybrid search; nil or unreachable = text only.
	Embedder search.Embedder
	// Exec runs the agent's run_query as agent_ro; nil = the tool reports itself unavailable.
	Exec *agent.Executor
	// AgentHTTP talks to the Python agent service at Cfg.AgentURL.
	AgentHTTP *http.Client

	zips *zipTickets
}

// Deps are the collaborators handlers need besides the config. Pool and Store are required.
type Deps struct {
	Pool      *pgxpool.Pool
	Store     *storage.Client
	Hub       *realtime.Hub
	Mailer    mail.Sender
	Version   string
	Embedder  search.Embedder
	AgentPool *pgxpool.Pool // dedicated pool connected as agent_ro_login (optional)
	AgentHTTP *http.Client  // optional override (tests)
}

// New wires a Server. The caller owns the pools and the hub.
func New(cfg config.Config, d Deps) *Server {
	s := &Server{
		Cfg:       cfg,
		Pool:      d.Pool,
		Q:         db.New(d.Pool),
		Store:     d.Store,
		Hub:       d.Hub,
		Mailer:    d.Mailer,
		Limits:    auth.NewMagicLinkLimits(),
		Version:   d.Version,
		Embedder:  d.Embedder,
		AgentHTTP: d.AgentHTTP,
		zips:      newZipTickets(10 * time.Minute),
	}
	if d.AgentPool != nil {
		s.Exec = &agent.Executor{Pool: d.AgentPool}
	}
	if s.AgentHTTP == nil {
		s.AgentHTTP = &http.Client{Timeout: agentProxyTimeout}
	}
	return s
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
	p        auth.Principal
	event    db.Event
	role     api.ViewerRole
	guest    *db.Guest    // the caller's guest row in this event, if any
	identity *db.Identity // the caller's identity (user or guest cookie), if one exists
	library  bool         // the "event" is the viewer's personal library (no events row)
}

// identityID is the identities.id of the viewer, or nil.
func (v viewer) identityID() []byte {
	if v.identity == nil {
		return nil
	}
	return v.identity.ID
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
	if !p.Anonymous() {
		id, err := s.identityFor(ctx, p)
		if err != nil {
			return v, err
		}
		v.identity = id
	}

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

// identityFor returns the identity row of the caller (user first, then guest cookie), or nil.
func (s *Server) identityFor(ctx context.Context, p auth.Principal) (*db.Identity, error) {
	if p.Anonymous() {
		return nil, nil
	}
	id, err := s.Q.GetIdentityForActor(ctx, db.GetIdentityForActorParams{UserID: p.UserID(), CookieID: p.CookieID})
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &id, nil
}

// libraryViewer is the viewer for an item without an event: only its owner may see it, as "owner".
func (s *Server) libraryViewer(ctx context.Context, m db.Medium) (viewer, error) {
	p := auth.FromContext(ctx)
	v := viewer{p: p, role: api.ViewerRoleAnonymous, library: true}
	if p.User != nil && m.OwnerID != nil && string(m.OwnerID) == string(p.User.ID) {
		v.role = api.ViewerRoleOwner
		id, err := s.identityFor(ctx, p)
		if err != nil {
			return v, err
		}
		v.identity = id
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
