package handlers

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
	"time"

	"yearbook/api/internal/apperr"
	api "yearbook/api/internal/gen/api"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/middleware"
	"yearbook/api/internal/realtime"
)

// pingInterval keeps proxies and browsers from closing idle streams.
const pingInterval = 20 * time.Second

// StreamEventUpdates is the Server-Sent Events endpoint for one event.
func (s *Server) StreamEventUpdates(ctx context.Context, req api.StreamEventUpdatesRequestObject) (api.StreamEventUpdatesResponseObject, error) {
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
	var lastID uint64
	if r := middleware.RequestFrom(ctx); r != nil {
		lastID, _ = strconv.ParseUint(r.Header.Get("Last-Event-ID"), 10, 64)
	}
	return sseResponse{ctx: ctx, hub: s.Hub, topic: ids.Encode(row.Event.ID), lastID: lastID}, nil
}

// sseResponse streams until the client disconnects. It is a custom response object because the
// generated one expects a finite io.Reader.
type sseResponse struct {
	ctx    context.Context
	hub    *realtime.Hub
	topic  string
	lastID uint64
}

func (r sseResponse) VisitStreamEventUpdatesResponse(w http.ResponseWriter) error {
	h := w.Header()
	h.Set("Content-Type", "text/event-stream; charset=utf-8")
	h.Set("Cache-Control", "no-cache, no-transform")
	h.Set("X-Accel-Buffering", "no")
	h.Set("Connection", "keep-alive")
	w.WriteHeader(http.StatusOK)

	rc := http.NewResponseController(w)
	flush := func() error { return rc.Flush() }
	write := func(e realtime.Event) error {
		if _, err := fmt.Fprintf(w, "id: %d\nevent: %s\ndata: %s\n\n", e.ID, e.Name, e.Data); err != nil {
			return err
		}
		return flush()
	}

	if _, err := fmt.Fprint(w, "retry: 5000\n\n"); err != nil {
		return nil
	}
	if err := flush(); err != nil {
		return nil
	}

	ch, replay, cancel := r.hub.Subscribe(r.topic, r.lastID)
	defer cancel()
	for _, e := range replay {
		if err := write(e); err != nil {
			return nil
		}
	}

	ticker := time.NewTicker(pingInterval)
	defer ticker.Stop()
	for {
		select {
		case <-r.ctx.Done():
			return nil
		case <-ticker.C:
			if _, err := fmt.Fprint(w, ": ping\n\n"); err != nil {
				return nil
			}
			if err := flush(); err != nil {
				return nil
			}
		case e, ok := <-ch:
			if !ok {
				return nil // dropped as a slow consumer; the browser reconnects with Last-Event-ID
			}
			if err := write(e); err != nil {
				return nil
			}
		}
	}
}
