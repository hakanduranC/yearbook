package handlers

import (
	"context"

	"yearbook/api/internal/apperr"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/jobs"
)

// LikeMedia records a like for the caller (user id or guest cookie id). Idempotent.
func (s *Server) LikeMedia(ctx context.Context, req api.LikeMediaRequestObject) (api.LikeMediaResponseObject, error) {
	res, err := s.setLike(ctx, req.MediaId, true)
	if err != nil {
		return nil, err
	}
	return api.LikeMedia200JSONResponse(res), nil
}

// UnlikeMedia removes the caller's like. Idempotent.
func (s *Server) UnlikeMedia(ctx context.Context, req api.UnlikeMediaRequestObject) (api.UnlikeMediaResponseObject, error) {
	res, err := s.setLike(ctx, req.MediaId, false)
	if err != nil {
		return nil, err
	}
	return api.UnlikeMedia200JSONResponse(res), nil
}

func (s *Server) setLike(ctx context.Context, id string, liked bool) (api.LikeResult, error) {
	m, v, err := s.requireViewable(ctx, id)
	if err != nil {
		return api.LikeResult{}, err
	}
	actor := v.p.Actor()
	if actor == nil {
		return api.LikeResult{}, apperr.Unauthorizedf("no identity; call POST /events/{slug}/guests first")
	}
	err = s.inTx(ctx, func(q *db.Queries) error {
		var err error
		if liked {
			err = q.AddLike(ctx, db.AddLikeParams{MediaID: m.ID, Actor: actor})
		} else {
			err = q.RemoveLike(ctx, db.RemoveLikeParams{MediaID: m.ID, Actor: actor})
		}
		if err != nil {
			return err
		}
		// Likes feed the quality score; the worker refreshes it once per minute per event.
		return jobs.EnqueueRecomputeScores(ctx, q, m.EventID)
	})
	if err != nil {
		return api.LikeResult{}, err
	}
	count, err := s.Q.CountLikes(ctx, m.ID)
	if err != nil {
		return api.LikeResult{}, err
	}
	s.publishLike(m.EventID, m.ID, int(count))
	return api.LikeResult{MediaId: ids.Encode(m.ID), LikeCount: int(count), Liked: liked}, nil
}
