package handlers

import (
	"context"

	"yearbook/api/internal/apperr"
	"yearbook/api/internal/auth"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
)

// Yearbook: the signed-in user's years, built from the persons linked to their identity.

// ListMyYears groups the events I own or appear in by year, newest first.
func (s *Server) ListMyYears(ctx context.Context, _ api.ListMyYearsRequestObject) (api.ListMyYearsResponseObject, error) {
	user, err := requireUser(ctx)
	if err != nil {
		return nil, err
	}
	identity, err := s.identityFor(ctx, auth.FromContext(ctx))
	if err != nil {
		return nil, err
	}
	v := viewer{p: auth.FromContext(ctx), identity: identity, library: true}
	rows, err := s.Q.ListMyYearEvents(ctx, db.ListMyYearEventsParams{IdentityID: v.identityID(), UserID: user.ID})
	if err != nil {
		return nil, err
	}
	out := api.ListMyYears200JSONResponse{Years: []api.YearSummary{}}
	index := map[int]int{}
	for _, r := range rows {
		year := int(r.Year)
		i, ok := index[year]
		if !ok {
			i = len(out.Years)
			index[year] = i
			out.Years = append(out.Years, api.YearSummary{Year: year, Events: []api.EventSummary{}})
		}
		summary, err := s.eventSummary(ctx, r, v, 4)
		if err != nil {
			return nil, err
		}
		out.Years[i].Events = append(out.Years[i].Events, summary)
		out.Years[i].Moments += int(r.OfYou)
	}
	return out, nil
}

// eventSummary shapes one yearbook event with up to n best photos of me.
func (s *Server) eventSummary(ctx context.Context, r db.ListMyYearEventsRow, v viewer, n int) (api.EventSummary, error) {
	analyzing := r.Analyzing && r.FacesEnabled
	out := api.EventSummary{Slug: r.Slug, Title: r.Title, StartsAt: r.StartsAt, Photos: int(r.Photos), OfYou: int(r.OfYou), Analyzing: &analyzing}
	if r.CoverMedia != nil {
		out.Cover = s.coverVariants(ctx, r.CoverMedia)
	} else if id, err := s.Q.GetEventCoverFallback(ctx, r.ID); err == nil {
		out.Cover = s.coverVariants(ctx, id)
	}
	if r.OfYou > 0 && v.identity != nil {
		best, err := s.Q.BestMediaOfMe(ctx, db.BestMediaOfMeParams{IdentityID: v.identity.ID, EventID: r.ID, RowLimit: int32(n)})
		if err != nil {
			return out, err
		}
		idList := make([][]byte, 0, len(best))
		for _, b := range best {
			idList = append(idList, b.ID)
		}
		rows, err := s.gridRows(ctx, idList, v)
		if err != nil {
			return out, err
		}
		items := make([]api.GridItem, 0, len(rows))
		for _, g := range rows {
			items = append(items, gridItemOf(s, g))
		}
		out.OfYouItems = &items
	}
	return out, nil
}

// GetMyYear is the recap of one year: events, the twelve best photos of me, the people I shared
// the most photos with, and a portrait.
func (s *Server) GetMyYear(ctx context.Context, req api.GetMyYearRequestObject) (api.GetMyYearResponseObject, error) {
	user, err := requireUser(ctx)
	if err != nil {
		return nil, err
	}
	if req.Year < 1970 || req.Year > 2200 {
		return nil, apperr.BadRequestf("year out of range")
	}
	year := int32(req.Year)
	identity, err := s.identityFor(ctx, auth.FromContext(ctx))
	if err != nil {
		return nil, err
	}
	v := viewer{p: auth.FromContext(ctx), identity: identity, library: true}
	rows, err := s.Q.ListMyYearEvents(ctx, db.ListMyYearEventsParams{IdentityID: v.identityID(), UserID: user.ID, Year: &year})
	if err != nil {
		return nil, err
	}
	out := api.YearRecap{Year: req.Year, Events: []api.EventSummary{}, BestOfYou: []api.GridItem{}, TopPeople: []api.TopPerson{}}
	for _, r := range rows {
		summary, err := s.eventSummary(ctx, r, v, 4)
		if err != nil {
			return nil, err
		}
		out.Events = append(out.Events, summary)
		out.Moments += int(r.OfYou)
	}
	if identity == nil {
		return api.GetMyYear200JSONResponse(out), nil
	}
	best, err := s.Q.BestMediaOfMe(ctx, db.BestMediaOfMeParams{IdentityID: identity.ID, Year: &year, RowLimit: 12})
	if err != nil {
		return nil, err
	}
	idList := make([][]byte, 0, len(best))
	for _, b := range best {
		idList = append(idList, b.ID)
	}
	grid, err := s.gridRows(ctx, idList, v)
	if err != nil {
		return nil, err
	}
	for _, g := range grid {
		out.BestOfYou = append(out.BestOfYou, gridItemOf(s, g))
	}
	people, err := s.Q.TopPeopleForMe(ctx, db.TopPeopleForMeParams{IdentityID: identity.ID, Year: year})
	if err != nil {
		return nil, err
	}
	for _, p := range people {
		tp := api.TopPerson{DisplayName: p.DisplayName, Count: int(p.Count)}
		if p.PersonID != nil {
			pid := ids.Encode(p.PersonID)
			tp.PersonId = &pid
		}
		if p.CoverFace != nil {
			u := CropURL(p.CoverFace)
			tp.CropUrl = &u
		}
		out.TopPeople = append(out.TopPeople, tp)
	}
	if portraitID, err := s.Q.PortraitOfMe(ctx, db.PortraitOfMeParams{IdentityID: identity.ID, Year: year}); err == nil {
		if rows, err := s.gridRows(ctx, [][]byte{portraitID}, v); err == nil && len(rows) == 1 {
			item := gridItemOf(s, rows[0])
			out.Portrait = &item
		}
	}
	return api.GetMyYear200JSONResponse(out), nil
}
