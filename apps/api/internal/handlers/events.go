package handlers

import (
	"bytes"
	"context"
	"crypto/rand"
	"errors"
	"fmt"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/skip2/go-qrcode"

	"yearbook/api/internal/apperr"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/media"
)

// ListEvents returns the events the user owns or is a member of.
func (s *Server) ListEvents(ctx context.Context, _ api.ListEventsRequestObject) (api.ListEventsResponseObject, error) {
	user, err := requireUser(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := s.Q.ListEventsForUser(ctx, user.ID)
	if err != nil {
		return nil, err
	}
	items := make([]api.Event, 0, len(rows))
	for _, row := range rows {
		v, err := s.viewerFor(ctx, row.Event)
		if err != nil {
			return nil, err
		}
		ev, err := s.eventJSON(ctx, row.Event, row.OwnerName, v)
		if err != nil {
			return nil, err
		}
		items = append(items, ev)
	}
	return api.ListEvents200JSONResponse{Items: items}, nil
}

// CreateEvent creates an event owned by the caller; the slug is the capability guests use.
func (s *Server) CreateEvent(ctx context.Context, req api.CreateEventRequestObject) (api.CreateEventResponseObject, error) {
	user, err := requireUser(ctx)
	if err != nil {
		return nil, err
	}
	if req.Body == nil {
		return nil, apperr.BadRequestf("body required")
	}
	title := strings.TrimSpace(req.Body.Title)
	if title == "" || len(title) > 120 {
		return nil, apperr.BadRequestf("title must be 1 to 120 characters")
	}
	tz := "Europe/Berlin"
	if req.Body.Timezone != nil && *req.Body.Timezone != "" {
		tz = *req.Body.Timezone
	}
	if _, err := time.LoadLocation(tz); err != nil {
		return nil, apperr.BadRequestf("unknown timezone")
	}
	if req.Body.EndsAt != nil && req.Body.EndsAt.Before(req.Body.StartsAt) {
		return nil, apperr.BadRequestf("ends_at must be after starts_at")
	}
	var created db.Event
	err = s.inTx(ctx, func(q *db.Queries) error {
		var err error
		created, err = q.CreateEvent(ctx, db.CreateEventParams{
			ID:       ids.New(),
			Slug:     NewSlug(title),
			Title:    title,
			StartsAt: req.Body.StartsAt,
			EndsAt:   req.Body.EndsAt,
			Timezone: tz,
			Location: req.Body.Location,
			OwnerID:  user.ID,
		})
		if err != nil {
			return err
		}
		return q.AddEventMember(ctx, db.AddEventMemberParams{EventID: created.ID, UserID: user.ID, Role: "owner"})
	})
	if err != nil {
		return nil, err
	}
	v := viewer{event: created, role: api.ViewerRoleOwner}
	ev, err := s.eventJSON(ctx, created, user.DisplayName, v)
	if err != nil {
		return nil, err
	}
	return api.CreateEvent201JSONResponse(ev), nil
}

// GetEvent returns the event with the caller's viewer context. Anyone with the slug may read it.
func (s *Server) GetEvent(ctx context.Context, req api.GetEventRequestObject) (api.GetEventResponseObject, error) {
	row, err := s.eventBySlug(ctx, req.Slug)
	if err != nil {
		return nil, err
	}
	v, err := s.viewerFor(ctx, row.Event)
	if err != nil {
		return nil, err
	}
	ev, err := s.eventJSON(ctx, row.Event, row.OwnerName, v)
	if err != nil {
		return nil, err
	}
	return api.GetEvent200JSONResponse(ev), nil
}

// UpdateEvent applies a partial update; hosts only.
func (s *Server) UpdateEvent(ctx context.Context, req api.UpdateEventRequestObject) (api.UpdateEventResponseObject, error) {
	row, err := s.eventBySlug(ctx, req.Slug)
	if err != nil {
		return nil, err
	}
	v, err := s.viewerFor(ctx, row.Event)
	if err != nil {
		return nil, err
	}
	if err := requireHost(v); err != nil {
		return nil, err
	}
	if req.Body == nil {
		return nil, apperr.BadRequestf("body required")
	}
	e := row.Event
	b := req.Body
	if b.Title != nil {
		t := strings.TrimSpace(*b.Title)
		if t == "" || len(t) > 120 {
			return nil, apperr.BadRequestf("title must be 1 to 120 characters")
		}
		e.Title = t
	}
	if b.StartsAt != nil {
		e.StartsAt = *b.StartsAt
	}
	if b.EndsAt != nil {
		e.EndsAt = b.EndsAt
	}
	if b.Timezone != nil {
		if _, err := time.LoadLocation(*b.Timezone); err != nil {
			return nil, apperr.BadRequestf("unknown timezone")
		}
		e.Timezone = *b.Timezone
	}
	if b.Location != nil {
		e.Location = b.Location
	}
	if b.GuestUpload != nil {
		e.GuestUpload = *b.GuestUpload
	}
	if b.GuestView != nil {
		e.GuestView = *b.GuestView
	}
	if b.CoverMediaId != nil {
		mid, err := ids.Decode(*b.CoverMediaId)
		if err != nil {
			return nil, apperr.BadRequestf("invalid cover_media_id")
		}
		m, err := s.Q.GetMedia(ctx, mid)
		if err != nil || string(m.EventID) != string(e.ID) || m.State != db.MediaStateReady {
			return nil, apperr.BadRequestf("cover_media_id must be a ready item of this event")
		}
		e.CoverMedia = mid
	}
	updated, err := s.Q.UpdateEvent(ctx, db.UpdateEventParams{
		ID: e.ID, Title: e.Title, StartsAt: e.StartsAt, EndsAt: e.EndsAt, Timezone: e.Timezone,
		Location: e.Location, CoverMedia: e.CoverMedia, GuestUpload: e.GuestUpload, GuestView: e.GuestView,
	})
	if err != nil {
		return nil, err
	}
	v.event = updated
	ev, err := s.eventJSON(ctx, updated, row.OwnerName, v)
	if err != nil {
		return nil, err
	}
	return api.UpdateEvent200JSONResponse(ev), nil
}

// DeleteEvent removes an event and, through cascades, everything in it. Owner only.
// Objects in storage are not deleted yet (a cleanup job is planned with the 30-day tombstones).
func (s *Server) DeleteEvent(ctx context.Context, req api.DeleteEventRequestObject) (api.DeleteEventResponseObject, error) {
	row, err := s.eventBySlug(ctx, req.Slug)
	if err != nil {
		return nil, err
	}
	v, err := s.viewerFor(ctx, row.Event)
	if err != nil {
		return nil, err
	}
	if v.role != api.ViewerRoleOwner {
		if v.p.User == nil {
			return nil, apperr.Unauthorizedf("")
		}
		return nil, apperr.Forbiddenf("only the owner can delete an event")
	}
	if err := s.Q.DeleteEvent(ctx, row.Event.ID); err != nil {
		return nil, err
	}
	return api.DeleteEvent204Response{}, nil
}

// GetEventStatus returns the processing counters.
func (s *Server) GetEventStatus(ctx context.Context, req api.GetEventStatusRequestObject) (api.GetEventStatusResponseObject, error) {
	row, err := s.eventBySlug(ctx, req.Slug)
	if err != nil {
		return nil, err
	}
	st, err := s.eventStatus(ctx, row.Event.ID)
	if err != nil {
		return nil, err
	}
	return api.GetEventStatus200JSONResponse(st), nil
}

// GetEventQr renders a QR code of the public event URL as SVG rects.
func (s *Server) GetEventQr(ctx context.Context, req api.GetEventQrRequestObject) (api.GetEventQrResponseObject, error) {
	row, err := s.eventBySlug(ctx, req.Slug)
	if err != nil {
		return nil, err
	}
	svg, err := QRSVG(s.eventURL(row.Event.Slug))
	if err != nil {
		return nil, err
	}
	return api.GetEventQr200ImagesvgXmlResponse{Body: bytes.NewReader(svg), ContentLength: int64(len(svg))}, nil
}

// eventURL is the public web URL guests open.
func (s *Server) eventURL(slug string) string {
	return strings.TrimRight(s.Cfg.WebOrigin, "/") + "/e/" + slug
}

// QRSVG encodes text as a QR code and renders every dark module as a 1x1 rect.
func QRSVG(text string) ([]byte, error) {
	qr, err := qrcode.New(text, qrcode.Medium)
	if err != nil {
		return nil, err
	}
	bitmap := qr.Bitmap() // includes the quiet zone
	n := len(bitmap)
	var b bytes.Buffer
	fmt.Fprintf(&b, `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" shape-rendering="crispEdges" role="img" aria-label="QR code">`, n, n)
	fmt.Fprintf(&b, `<rect width="%d" height="%d" fill="#ffffff"/>`, n, n)
	for y, rowBits := range bitmap {
		for x, dark := range rowBits {
			if dark {
				fmt.Fprintf(&b, `<rect x="%d" y="%d" width="1" height="1" fill="#141414"/>`, x, y)
			}
		}
	}
	b.WriteString(`</svg>`)
	return b.Bytes(), nil
}

// eventJSON assembles the Event shape: counts, cover variants, host name and viewer.
func (s *Server) eventJSON(ctx context.Context, e db.Event, ownerName string, v viewer) (api.Event, error) {
	counts, err := s.Q.GetEventCounts(ctx, e.ID)
	if err != nil {
		return api.Event{}, err
	}
	out := api.Event{
		Id:          ids.Encode(e.ID),
		Slug:        e.Slug,
		Title:       e.Title,
		StartsAt:    e.StartsAt,
		EndsAt:      e.EndsAt,
		Timezone:    e.Timezone,
		Location:    e.Location,
		GuestUpload: e.GuestUpload,
		GuestView:   e.GuestView,
		CreatedAt:   e.CreatedAt,
		Counts: api.EventCounts{
			Photos: int(counts.Photos), Videos: int(counts.Videos), Ready: int(counts.Ready),
			Processing: int(counts.Processing), Failed: int(counts.Failed),
		},
		Viewer: api.Viewer{Role: v.role},
	}
	out.Host.DisplayName = ownerName
	if v.guest != nil {
		gid := ids.Encode(v.guest.ID)
		out.Viewer.GuestId = &gid
		out.Viewer.DisplayName = v.guest.DisplayName
	}
	if v.p.User != nil {
		out.Viewer.DisplayName = &v.p.User.DisplayName
	}
	coverID := e.CoverMedia
	if coverID == nil {
		// No explicit cover yet: fall back to the newest ready photo so link previews have an image.
		if id, err := s.Q.GetEventCoverFallback(ctx, e.ID); err == nil {
			coverID = id
		} else if !errors.Is(err, pgx.ErrNoRows) {
			return api.Event{}, err
		}
	}
	if coverID != nil {
		variants, err := s.Q.GetVariants(ctx, coverID)
		if err != nil {
			return api.Event{}, err
		}
		keys := map[string]string{}
		for _, vr := range variants {
			keys[vr.Name] = vr.Key
		}
		out.Cover = media.VariantsFromKeys(keys, s.Store.PublicURL)
	}
	return out, nil
}

// eventStatus maps the counters query onto EventStatus.
func (s *Server) eventStatus(ctx context.Context, eventID []byte) (api.EventStatus, error) {
	c, err := s.Q.GetEventCounts(ctx, eventID)
	if err != nil {
		return api.EventStatus{}, err
	}
	return api.EventStatus{Total: int(c.Total), Ready: int(c.Ready), Processing: int(c.Processing), Failed: int(c.Failed)}, nil
}

// requireHost returns 401 for anonymous callers and 403 for non-hosts.
func requireHost(v viewer) error {
	if v.isHost() {
		return nil
	}
	if v.p.User == nil {
		return apperr.Unauthorizedf("")
	}
	return apperr.Forbiddenf("hosts only")
}

var nonSlug = regexp.MustCompile(`[^a-z0-9]+`)

// NewSlug builds "slugified-title-xxxxxx" with six random base32 characters.
func NewSlug(title string) string {
	t := strings.ToLower(title)
	t = strings.NewReplacer("ä", "ae", "ö", "oe", "ü", "ue", "ß", "ss").Replace(t)
	t = strings.Trim(nonSlug.ReplaceAllString(t, "-"), "-")
	if len(t) > 40 {
		t = strings.Trim(t[:40], "-")
	}
	if t == "" {
		t = "event"
	}
	return t + "-" + randomBase32(6)
}

const base32Alphabet = "abcdefghijklmnopqrstuvwxyz234567"

func randomBase32(n int) string {
	raw := make([]byte, n)
	rand.Read(raw)
	out := make([]byte, n)
	for i, b := range raw {
		out[i] = base32Alphabet[int(b)%len(base32Alphabet)]
	}
	return string(out)
}

// mediaByID loads a media row or returns 404 (removed items are 404 too).
func (s *Server) mediaByID(ctx context.Context, id string) (db.Medium, error) {
	raw, err := ids.Decode(id)
	if err != nil {
		return db.Medium{}, apperr.NotFoundf("media not found")
	}
	m, err := s.Q.GetMedia(ctx, raw)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && m.State == db.MediaStateRemoved) {
		return db.Medium{}, apperr.NotFoundf("media not found")
	}
	return m, err
}

// viewerForMedia resolves the viewer in the media item's event.
func (s *Server) viewerForMedia(ctx context.Context, m db.Medium) (viewer, error) {
	if m.EventID == nil {
		return viewer{}, apperr.NotFoundf("media not found") // library items come with M1.5
	}
	row, err := s.Q.GetEventByID(ctx, m.EventID)
	if err != nil {
		return viewer{}, err
	}
	return s.viewerFor(ctx, row.Event)
}

// statusNoContent is a helper for custom Visit implementations.
func statusNoContent(w http.ResponseWriter) error {
	w.WriteHeader(http.StatusNoContent)
	return nil
}
