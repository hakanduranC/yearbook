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
		Actor:   v.p.Actor(),
		UserID:  v.p.UserID(),
		GuestID: v.guestID(),
		Ids:     idList,
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
	raw, err := ids.Decode(n.MediaID)
	if err != nil {
		return "", nil, false
	}
	switch n.Type {
	case "media.ready":
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
	s.Hub.Publish(ids.Encode(eventID), "media.queued", map[string]any{"id": ids.Encode(mediaID), "mine": false})
}

func (s *Server) publishRemoved(eventID, mediaID []byte) {
	s.Hub.Publish(ids.Encode(eventID), "media.removed", map[string]any{"id": ids.Encode(mediaID)})
}

func (s *Server) publishLike(eventID, mediaID []byte, count int) {
	s.Hub.Publish(ids.Encode(eventID), "like.changed", map[string]any{"media_id": ids.Encode(mediaID), "like_count": count})
}
