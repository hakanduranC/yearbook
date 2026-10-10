package handlers

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"

	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/media"
	"yearbook/api/internal/realtime"
)

// gridRows loads the grid rows for ids as seen by viewer v, in the order of ids.
// v may be the zero viewer for viewer-independent loads (SSE broadcasts).
func (s *Server) gridRows(ctx context.Context, idList [][]byte, v viewer) ([]db.GetGridRowsRow, error) {
	if len(idList) == 0 {
		return nil, nil
	}
	rows, err := s.Q.GetGridRows(ctx, db.GetGridRowsParams{
		Actor:      v.p.Actor(),
		UserID:     v.p.UserID(),
		GuestID:    v.guestID(),
		IdentityID: v.identityID(),
		Ids:        idList,
	})
	if err != nil {
		return nil, err
	}
	byID := make(map[string]db.GetGridRowsRow, len(rows))
	for _, r := range rows {
		byID[string(r.ID)] = r
	}
	ordered := make([]db.GetGridRowsRow, 0, len(idList))
	for _, id := range idList {
		if r, ok := byID[string(id)]; ok {
			ordered = append(ordered, r)
		}
	}
	return ordered, nil
}

// gridItem loads one GridItem for the viewer.
func (s *Server) gridItem(ctx context.Context, id []byte, v viewer) (api.GridItem, error) {
	rows, err := s.gridRows(ctx, [][]byte{id}, v)
	if err != nil {
		return api.GridItem{}, err
	}
	if len(rows) == 0 {
		return api.GridItem{}, pgx.ErrNoRows
	}
	return media.GridItemFromRow(rows[0], s.Store.PublicURL), nil
}

// TranslateNotification turns worker notifications into SSE events. media.ready carries the
// viewer-independent GridItem (liked/me/mine are false in broadcasts).
func (s *Server) TranslateNotification(ctx context.Context, n realtime.Notification) (string, any, bool) {
	if n.Type == "people.updated" {
		// The clusterer finished: tell open People tabs to refetch.
		if n.EventID == nil {
			return "", nil, false
		}
		eid, err := ids.Decode(*n.EventID)
		if err != nil {
			return "", nil, false
		}
		ev, err := s.Q.GetEventByID(ctx, eid)
		if err != nil {
			return "", nil, false
		}
		return "people.updated", map[string]any{"event_slug": ev.Event.Slug}, true
	}
	raw, err := ids.Decode(n.MediaID)
	if err != nil {
		return "", nil, false
	}
	switch n.Type {
	case "media.ready", "media.analyzed":
		// media.analyzed re-sends the GridItem (now with analyzed=true and person_ids) under the
		// media.ready name, which is the event clients already patch their cache on.
		item, err := s.gridItem(ctx, raw, viewer{})
		if err != nil {
			if !errors.Is(err, pgx.ErrNoRows) {
				logErr(ctx, "load grid item for media.ready", err)
			}
			return "", nil, false
		}
		return "media.ready", item, true
	case "media.failed":
		code := "failed"
		if m, err := s.Q.GetMedia(ctx, raw); err == nil && m.Error != nil && *m.Error != "" {
			code = *m.Error
		}
		return "media.failed", map[string]any{"id": n.MediaID, "code": code}, true
	default:
		return "", nil, false
	}
}

// publishQueued/publishRemoved/publishLike are the API-originated SSE events.
func (s *Server) publishQueued(eventID, mediaID []byte) {
	if eventID == nil {
		return
	}
	s.Hub.Publish(ids.Encode(eventID), "media.queued", map[string]any{"id": ids.Encode(mediaID), "mine": false})
}

func (s *Server) publishRemoved(eventID, mediaID []byte) {
	if eventID == nil {
		return
	}
	s.Hub.Publish(ids.Encode(eventID), "media.removed", map[string]any{"id": ids.Encode(mediaID)})
}

func (s *Server) publishLike(eventID, mediaID []byte, count int) {
	if eventID == nil {
		return
	}
	s.Hub.Publish(ids.Encode(eventID), "like.changed", map[string]any{"media_id": ids.Encode(mediaID), "like_count": count})
}

// publishPeople tells open People tabs of an event that persons changed (claim, merge, split, ...).
func (s *Server) publishPeople(eventID []byte, slug string) {
	if eventID == nil {
		return
	}
	s.Hub.Publish(ids.Encode(eventID), "people.updated", map[string]any{"event_slug": slug})
}

// gridItemOf is GridItemFromRow with the server's URL builder.
func gridItemOf(s *Server, r db.GetGridRowsRow) api.GridItem {
	return media.GridItemFromRow(r, s.Store.PublicURL)
}
