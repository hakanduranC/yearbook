package handlers

import (
	"context"
	"strings"
	"time"

	"yearbook/api/internal/apperr"
	"yearbook/api/internal/auth"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/search"
)

// SearchEventMedia is hybrid text search inside one event (no language model).
func (s *Server) SearchEventMedia(ctx context.Context, req api.SearchEventMediaRequestObject) (api.SearchEventMediaResponseObject, error) {
	row, err := s.eventBySlug(ctx, req.Slug)
	if err != nil {
		return nil, err
	}
	v, err := s.viewerFor(ctx, row.Event)
	if err != nil {
		return nil, err
	}
	if !v.canView() {
		return nil, apperr.Forbiddenf("the host has closed this album")
	}
	q := strings.TrimSpace(req.Params.Q)
	if q == "" || len(q) > 200 {
		return nil, apperr.BadRequestf("q must be 1 to 200 characters")
	}
	limit := 60
	if req.Params.Limit != nil {
		limit = min(max(*req.Params.Limit, 1), 200)
	}
	scope := search.Scope{EventIDs: [][]byte{row.Event.ID}, UserID: v.p.UserID(), GuestID: v.guestID(), IdentityID: v.identityID(), Actor: v.p.Actor()}
	page, err := s.searchPage(ctx, scope, search.Filters{Text: q, Limit: limit}, v, locationOf(row.Event.Timezone))
	if err != nil {
		return nil, err
	}
	return api.SearchEventMedia200JSONResponse(page), nil
}

// SearchMyMedia searches across every event the user can see and their library.
func (s *Server) SearchMyMedia(ctx context.Context, req api.SearchMyMediaRequestObject) (api.SearchMyMediaResponseObject, error) {
	user, err := requireUser(ctx)
	if err != nil {
		return nil, err
	}
	q := strings.TrimSpace(req.Params.Q)
	if q == "" || len(q) > 200 {
		return nil, apperr.BadRequestf("q must be 1 to 200 characters")
	}
	limit := 60
	if req.Params.Limit != nil {
		limit = min(max(*req.Params.Limit, 1), 200)
	}
	p := auth.FromContext(ctx)
	identity, err := s.identityFor(ctx, p)
	if err != nil {
		return nil, err
	}
	eventIDs, err := s.Q.ListVisibleEventIDs(ctx, db.ListVisibleEventIDsParams{UserID: user.ID, CookieID: p.CookieID})
	if err != nil {
		return nil, err
	}
	v := viewer{p: p, identity: identity, library: true}
	scope := search.Scope{EventIDs: eventIDs, IncludeLibrary: true, UserID: user.ID, IdentityID: v.identityID(), Actor: p.Actor()}
	page, err := s.searchPage(ctx, scope, search.Filters{Text: q, Limit: limit}, v, time.UTC)
	if err != nil {
		return nil, err
	}
	return api.SearchMyMedia200JSONResponse(page), nil
}

// searchPage runs the hybrid query and shapes a MediaPage (best match first, no cursor).
func (s *Server) searchPage(ctx context.Context, scope search.Scope, f search.Filters, v viewer, loc *time.Location) (api.MediaPage, error) {
	results, err := search.Run(ctx, s.Q, s.Embedder, scope, f)
	if err != nil {
		return api.MediaPage{}, err
	}
	idList := make([][]byte, 0, len(results))
	times := make([]time.Time, 0, len(results))
	for _, r := range results {
		idList = append(idList, r.ID)
		times = append(times, r.SortAt)
	}
	return s.buildPage(ctx, idList, times, v, loc)
}
