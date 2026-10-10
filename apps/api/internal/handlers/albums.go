package handlers

import (
	"context"
	"errors"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"yearbook/api/internal/apperr"
	"yearbook/api/internal/auth"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/media"
)

// Share principal ------------------------------------------------------------------------------
//
// A share link is the third principal kind (SDD §6). The web app passes the share id as
// `?share=<id>` on media requests made from /s/{share_id}; the Principal middleware resolves it
// into auth.Principal.Share. The media endpoints then accept the request when the item belongs to
// the shared album, and allow originals/zips only when the share has allow_download.

// sharedWith reports whether the viewer's share principal covers mediaID. download requires
// allow_download on the share.
func (s *Server) sharedWith(ctx context.Context, v viewer, mediaID []byte, download bool) bool {
	sh := v.p.Share
	if sh == nil {
		return false
	}
	if download && !sh.AllowDownload {
		return false
	}
	ok, err := s.Q.AlbumContains(ctx, db.AlbumContainsParams{AlbumID: sh.AlbumID, MediaID: mediaID})
	return err == nil && ok
}

// albumCtx is an album with its event (when it has one) and the caller's viewer in that event.
type albumCtx struct {
	album db.Album
	ev    *db.GetEventByIDRow
	v     viewer
}

// canEdit: the album's owner, or a host of its event.
func (a albumCtx) canEdit() bool {
	actor := a.v.p.Actor()
	if actor != nil && string(a.album.Owner) == string(actor) {
		return true
	}
	return a.ev != nil && a.v.isHost()
}

// canView: anyone who may see the event; for albums without an event, the owner.
func (a albumCtx) canView() bool {
	if a.ev != nil {
		return a.v.canView()
	}
	return a.canEdit()
}

func (s *Server) albumByID(ctx context.Context, id string) (albumCtx, error) {
	raw, err := ids.Decode(id)
	if err != nil {
		return albumCtx{}, apperr.NotFoundf("album not found")
	}
	a, err := s.Q.GetAlbum(ctx, raw)
	if errors.Is(err, pgx.ErrNoRows) {
		return albumCtx{}, apperr.NotFoundf("album not found")
	}
	if err != nil {
		return albumCtx{}, err
	}
	ac := albumCtx{album: a}
	if a.EventID != nil {
		ev, err := s.Q.GetEventByID(ctx, a.EventID)
		if err != nil {
			return ac, err
		}
		ac.ev = &ev
		ac.v, err = s.viewerFor(ctx, ev.Event)
		if err != nil {
			return ac, err
		}
	} else {
		ac.v = viewer{p: auth.FromContext(ctx), library: true}
		if id, err := s.identityFor(ctx, ac.v.p); err == nil {
			ac.v.identity = id
		}
	}
	return ac, nil
}

func (s *Server) albumJSON(ctx context.Context, ac albumCtx) (api.Album, error) {
	count, err := s.Q.AlbumCount(ctx, ac.album.ID)
	if err != nil {
		return api.Album{}, err
	}
	out := api.Album{Id: ids.Encode(ac.album.ID), Title: ac.album.Title, Kind: api.AlbumKind(ac.album.Kind), Count: int(count)}
	canEdit := ac.canEdit()
	out.CanEdit = &canEdit
	if ac.ev != nil {
		slug := ac.ev.Event.Slug
		out.EventSlug = &slug
	}
	if cover, err := s.Q.AlbumCover(ctx, ac.album.ID); err == nil {
		out.Cover = s.coverVariants(ctx, cover)
	}
	return out, nil
}

// coverVariants loads the public variant URLs of one item (nil when none exist yet).
func (s *Server) coverVariants(ctx context.Context, mediaID []byte) *api.Variants {
	variants, err := s.Q.GetVariants(ctx, mediaID)
	if err != nil {
		return nil
	}
	keys := map[string]string{}
	for _, vr := range variants {
		keys[vr.Name] = vr.Key
	}
	return media.VariantsFromKeys(keys, s.Store.PublicURL)
}

func (s *Server) albumDetail(ctx context.Context, ac albumCtx, allowDownload bool) (api.AlbumDetail, error) {
	a, err := s.albumJSON(ctx, ac)
	if err != nil {
		return api.AlbumDetail{}, err
	}
	rows, err := s.Q.ListAlbumMediaIDs(ctx, ac.album.ID)
	if err != nil {
		return api.AlbumDetail{}, err
	}
	idList := make([][]byte, 0, len(rows))
	for _, r := range rows {
		idList = append(idList, r.MediaID)
	}
	grid, err := s.gridRows(ctx, idList, ac.v)
	if err != nil {
		return api.AlbumDetail{}, err
	}
	d := api.AlbumDetail{
		Id: a.Id, Title: a.Title, Kind: api.AlbumDetailKind(a.Kind), Count: a.Count, Cover: a.Cover, CanEdit: a.CanEdit,
		EventSlug: a.EventSlug, Items: make([]api.GridItem, 0, len(grid)), AllowDownload: allowDownload,
	}
	if ac.ev != nil {
		title := ac.ev.Event.Title
		d.EventTitle = &title
	}
	for _, r := range grid {
		d.Items = append(d.Items, media.GridItemFromRow(r, s.Store.PublicURL))
	}
	return d, nil
}

// ListEventAlbums lists the albums of an event.
func (s *Server) ListEventAlbums(ctx context.Context, req api.ListEventAlbumsRequestObject) (api.ListEventAlbumsResponseObject, error) {
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
	rows, err := s.Q.ListEventAlbums(ctx, row.Event.ID)
	if err != nil {
		return nil, err
	}
	ev := db.GetEventByIDRow{Event: row.Event, OwnerName: row.OwnerName}
	out := api.ListEventAlbums200JSONResponse{Albums: make([]api.Album, 0, len(rows))}
	for _, r := range rows {
		ac := albumCtx{album: db.Album{ID: r.ID, EventID: r.EventID, Owner: r.Owner, Title: r.Title, Kind: r.Kind, CreatedAt: r.CreatedAt}, ev: &ev, v: v}
		a := api.Album{Id: ids.Encode(r.ID), Title: r.Title, Kind: api.AlbumKind(r.Kind), Count: int(r.Count)}
		canEdit := ac.canEdit()
		a.CanEdit = &canEdit
		slug := row.Event.Slug
		a.EventSlug = &slug
		if r.CoverMedia != nil {
			a.Cover = s.coverVariants(ctx, r.CoverMedia)
		}
		out.Albums = append(out.Albums, a)
	}
	return out, nil
}

// CreateAlbum creates a manual album, inside an event (any identified viewer) or in the caller's
// library (users only). Items outside the album's event are ignored.
func (s *Server) CreateAlbum(ctx context.Context, req api.CreateAlbumRequestObject) (api.CreateAlbumResponseObject, error) {
	if req.Body == nil {
		return nil, apperr.BadRequestf("body required")
	}
	a, err := s.createAlbum(ctx, req.Body.EventSlug, req.Body.Title, req.Body.MediaIds, "manual")
	if err != nil {
		return nil, err
	}
	return api.CreateAlbum201JSONResponse(a), nil
}

// createAlbum is shared with the agent's create_album tool.
func (s *Server) createAlbum(ctx context.Context, eventSlug *string, title string, mediaIDs []api.Id, kind string) (api.Album, error) {
	title = strings.TrimSpace(title)
	if title == "" || len(title) > 120 {
		return api.Album{}, apperr.BadRequestf("title must be 1 to 120 characters")
	}
	p := auth.FromContext(ctx)
	if p.Anonymous() {
		return api.Album{}, apperr.Unauthorizedf("no identity; call POST /events/{slug}/guests first")
	}
	var eventID []byte
	var ev *db.GetEventByIDRow
	var v viewer
	if eventSlug != nil && *eventSlug != "" {
		row, err := s.eventBySlug(ctx, *eventSlug)
		if err != nil {
			return api.Album{}, err
		}
		v, err = s.viewerFor(ctx, row.Event)
		if err != nil {
			return api.Album{}, err
		}
		if !v.canView() {
			return api.Album{}, apperr.Forbiddenf("the host has closed this album")
		}
		eventID = row.Event.ID
		e := db.GetEventByIDRow{Event: row.Event, OwnerName: row.OwnerName}
		ev = &e
	} else if p.User == nil {
		return api.Album{}, apperr.BadRequestf("event_slug required for guests")
	} else {
		v = viewer{p: p, library: true}
	}
	raw := make([][]byte, 0, len(mediaIDs))
	for _, id := range mediaIDs {
		b, err := ids.Decode(id)
		if err != nil {
			return api.Album{}, apperr.BadRequestf("invalid media id " + id)
		}
		raw = append(raw, b)
	}
	items, err := s.Q.ListMediaByIDs(ctx, raw)
	if err != nil {
		return api.Album{}, err
	}
	allowed := map[string]bool{}
	for _, m := range items {
		switch {
		case eventID != nil:
			allowed[string(m.ID)] = string(m.EventID) == string(eventID)
		default: // library album: my own items or items of events I can see
			if m.OwnerID != nil && string(m.OwnerID) == string(p.User.ID) {
				allowed[string(m.ID)] = true
			} else if m.EventID != nil {
				if e, err := s.Q.GetEventByID(ctx, m.EventID); err == nil {
					if mv, err := s.viewerFor(ctx, e.Event); err == nil {
						allowed[string(m.ID)] = mv.canView()
					}
				}
			}
		}
	}
	album := db.Album{}
	err = s.inTx(ctx, func(q *db.Queries) error {
		var err error
		album, err = q.CreateAlbum(ctx, db.CreateAlbumParams{ID: ids.New(), EventID: eventID, Owner: p.Actor(), Title: title, Kind: kind})
		if err != nil {
			return err
		}
		pos := int32(0)
		for _, id := range raw {
			if !allowed[string(id)] {
				continue
			}
			if err := q.AddAlbumItem(ctx, db.AddAlbumItemParams{AlbumID: album.ID, MediaID: id, Position: pos}); err != nil {
				return err
			}
			pos++
		}
		return nil
	})
	if err != nil {
		return api.Album{}, err
	}
	return s.albumJSON(ctx, albumCtx{album: album, ev: ev, v: v})
}

// GetAlbum returns an album with its items.
func (s *Server) GetAlbum(ctx context.Context, req api.GetAlbumRequestObject) (api.GetAlbumResponseObject, error) {
	ac, err := s.albumByID(ctx, req.AlbumId)
	if err != nil {
		return nil, err
	}
	if !ac.canView() {
		return nil, apperr.Forbiddenf("")
	}
	d, err := s.albumDetail(ctx, ac, true)
	if err != nil {
		return nil, err
	}
	return api.GetAlbum200JSONResponse(d), nil
}

// UpdateAlbum renames, adds or removes items. Owner or host.
func (s *Server) UpdateAlbum(ctx context.Context, req api.UpdateAlbumRequestObject) (api.UpdateAlbumResponseObject, error) {
	ac, err := s.albumByID(ctx, req.AlbumId)
	if err != nil {
		return nil, err
	}
	if !ac.canEdit() {
		return nil, apperr.Forbiddenf("only the album's owner or a host can change it")
	}
	if req.Body == nil {
		return nil, apperr.BadRequestf("body required")
	}
	err = s.inTx(ctx, func(q *db.Queries) error {
		if req.Body.Title != nil {
			t := strings.TrimSpace(*req.Body.Title)
			if t == "" || len(t) > 120 {
				return apperr.BadRequestf("title must be 1 to 120 characters")
			}
			if err := q.UpdateAlbumTitle(ctx, db.UpdateAlbumTitleParams{ID: ac.album.ID, Title: t}); err != nil {
				return err
			}
		}
		if req.Body.Remove != nil {
			rm := make([][]byte, 0, len(*req.Body.Remove))
			for _, id := range *req.Body.Remove {
				if b, err := ids.Decode(id); err == nil {
					rm = append(rm, b)
				}
			}
			if err := q.RemoveAlbumItems(ctx, db.RemoveAlbumItemsParams{AlbumID: ac.album.ID, MediaIds: rm}); err != nil {
				return err
			}
		}
		if req.Body.Add != nil {
			pos, err := q.AlbumMaxPosition(ctx, ac.album.ID)
			if err != nil {
				return err
			}
			for _, id := range *req.Body.Add {
				b, err := ids.Decode(id)
				if err != nil {
					return apperr.BadRequestf("invalid media id " + id)
				}
				m, err := q.GetMedia(ctx, b)
				if err != nil || m.State == db.MediaStateRemoved {
					continue
				}
				if ac.album.EventID != nil && string(m.EventID) != string(ac.album.EventID) {
					continue
				}
				pos++
				if err := q.AddAlbumItem(ctx, db.AddAlbumItemParams{AlbumID: ac.album.ID, MediaID: b, Position: pos}); err != nil {
					return err
				}
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	ac, err = s.albumByID(ctx, req.AlbumId)
	if err != nil {
		return nil, err
	}
	d, err := s.albumDetail(ctx, ac, true)
	if err != nil {
		return nil, err
	}
	return api.UpdateAlbum200JSONResponse(d), nil
}

// DeleteAlbum removes an album (and its shares). Owner or host.
func (s *Server) DeleteAlbum(ctx context.Context, req api.DeleteAlbumRequestObject) (api.DeleteAlbumResponseObject, error) {
	ac, err := s.albumByID(ctx, req.AlbumId)
	if err != nil {
		return nil, err
	}
	if !ac.canEdit() {
		return nil, apperr.Forbiddenf("only the album's owner or a host can delete it")
	}
	if err := s.Q.DeleteAlbum(ctx, ac.album.ID); err != nil {
		return nil, err
	}
	return api.DeleteAlbum204Response{}, nil
}

// ShareAlbum creates a read-only link. Owner or host.
func (s *Server) ShareAlbum(ctx context.Context, req api.ShareAlbumRequestObject) (api.ShareAlbumResponseObject, error) {
	ac, err := s.albumByID(ctx, req.AlbumId)
	if err != nil {
		return nil, err
	}
	if !ac.canEdit() {
		return nil, apperr.Forbiddenf("only the album's owner or a host can share it")
	}
	allow := true
	var expires *time.Time
	if req.Body != nil {
		if req.Body.AllowDownload != nil {
			allow = *req.Body.AllowDownload
		}
		if req.Body.ExpiresDays != nil {
			d := min(max(*req.Body.ExpiresDays, 1), 365)
			t := time.Now().UTC().Add(time.Duration(d) * 24 * time.Hour)
			expires = &t
		}
	}
	sh, err := s.shareAlbum(ctx, ac.album.ID, ac.v.p.Actor(), expires, allow)
	if err != nil {
		return nil, err
	}
	return api.ShareAlbum201JSONResponse(sh), nil
}

// shareAlbum is shared with the agent's share_album tool.
func (s *Server) shareAlbum(ctx context.Context, albumID, actor []byte, expires *time.Time, allow bool) (api.Share, error) {
	sh, err := s.Q.CreateShare(ctx, db.CreateShareParams{ID: ids.New(), AlbumID: albumID, CreatedBy: actor, ExpiresAt: expires, AllowDownload: allow})
	if err != nil {
		return api.Share{}, err
	}
	return api.Share{
		ShareId: ids.Encode(sh.ID), Url: strings.TrimRight(s.Cfg.WebOrigin, "/") + "/s/" + ids.Encode(sh.ID),
		ExpiresAt: sh.ExpiresAt, AllowDownload: sh.AllowDownload,
	}, nil
}

// GetSharedAlbum is the public view of a shared album. Expired or unknown links are 404.
func (s *Server) GetSharedAlbum(ctx context.Context, req api.GetSharedAlbumRequestObject) (api.GetSharedAlbumResponseObject, error) {
	raw, err := ids.Decode(req.ShareId)
	if err != nil {
		return nil, apperr.NotFoundf("this link is not valid")
	}
	sh, err := s.Q.GetShare(ctx, raw)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, apperr.NotFoundf("this link has expired or does not exist")
	}
	if err != nil {
		return nil, err
	}
	a, err := s.Q.GetAlbum(ctx, sh.AlbumID)
	if err != nil {
		return nil, apperr.NotFoundf("this link has expired or does not exist")
	}
	ac := albumCtx{album: a, v: viewer{p: auth.Principal{Share: &sh}}}
	if a.EventID != nil {
		ev, err := s.Q.GetEventByID(ctx, a.EventID)
		if err == nil {
			ac.ev = &ev
		}
	}
	d, err := s.albumDetail(ctx, ac, sh.AllowDownload)
	if err != nil {
		return nil, err
	}
	canEdit := false
	d.CanEdit = &canEdit
	return api.GetSharedAlbum200JSONResponse(d), nil
}
