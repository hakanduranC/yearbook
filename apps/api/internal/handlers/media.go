package handlers

import (
	"context"
	"errors"
	"net/http"
	"path"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"yearbook/api/internal/apperr"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/jobs"
	"yearbook/api/internal/media"
)

// deleteWindow is how long an uploader may delete their own item from the same browser.
const deleteWindow = 7 * 24 * time.Hour

// ListEventMedia returns one page of the grid, newest capture first, with time-of-day groups.
func (s *Server) ListEventMedia(ctx context.Context, req api.ListEventMediaRequestObject) (api.ListEventMediaResponseObject, error) {
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
	filter := api.All
	if req.Params.Filter != nil {
		filter = *req.Params.Filter
	}
	switch filter {
	case api.All, api.Best, api.Videos, api.Mine:
	default:
		return nil, apperr.BadRequestf("filter must be all, best, videos or mine")
	}
	limit := 60
	if req.Params.Limit != nil {
		limit = min(max(*req.Params.Limit, 1), 200)
	}
	cursor := media.Cursor{}
	if req.Params.Cursor != nil {
		if cursor, err = media.DecodeCursor(*req.Params.Cursor); err != nil {
			return nil, apperr.BadRequestf("invalid cursor")
		}
	}

	// Fetch one extra row to learn whether a next page exists.
	var idList [][]byte
	var times []time.Time
	var scores []float32
	if filter == api.Best {
		rows, err := s.Q.ListMediaIDsBest(ctx, db.ListMediaIDsBestParams{
			EventID: row.Event.ID, CursorID: cursor.ID, CursorAt: cursor.At, CursorScore: cursor.Score, RowLimit: int32(limit + 1),
		})
		if err != nil {
			return nil, err
		}
		for _, r := range rows {
			idList, times, scores = append(idList, r.ID), append(times, r.SortAt), append(scores, r.Score)
		}
	} else {
		rows, err := s.Q.ListMediaIDs(ctx, db.ListMediaIDsParams{
			EventID: row.Event.ID, Filter: string(filter), UserID: v.p.UserID(), GuestID: v.guestID(),
			CursorID: cursor.ID, CursorAt: cursor.At, RowLimit: int32(limit + 1),
		})
		if err != nil {
			return nil, err
		}
		for _, r := range rows {
			idList, times = append(idList, r.ID), append(times, r.SortAt)
		}
	}

	page := api.MediaPage{Items: []api.GridItem{}, Groups: []api.MediaGroup{}}
	if len(idList) > limit {
		last := limit - 1
		c := media.Cursor{At: times[last], ID: idList[last]}
		if filter == api.Best {
			c.Score = scores[last]
		}
		next := c.Encode(filter == api.Best)
		page.NextCursor = &next
		idList, times = idList[:limit], times[:limit]
	}

	gridRows, err := s.gridRows(ctx, idList, v)
	if err != nil {
		return nil, err
	}
	for _, r := range gridRows {
		page.Items = append(page.Items, media.GridItemFromRow(r, s.Store.PublicURL))
	}
	loc, err := time.LoadLocation(row.Event.Timezone)
	if err != nil {
		loc = time.UTC
	}
	page.Groups = media.Groups(times, loc)
	return api.ListEventMedia200JSONResponse(page), nil
}

// GetMedia returns one item with uploader and permissions.
func (s *Server) GetMedia(ctx context.Context, req api.GetMediaRequestObject) (api.GetMediaResponseObject, error) {
	m, err := s.mediaByID(ctx, req.MediaId)
	if err != nil {
		return nil, err
	}
	v, err := s.viewerForMedia(ctx, m)
	if err != nil {
		return nil, err
	}
	if !v.canView() && !isUploader(m, v) {
		return nil, apperr.Forbiddenf("the host has closed this album")
	}
	rows, err := s.gridRows(ctx, [][]byte{m.ID}, v)
	if err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return nil, apperr.NotFoundf("media not found")
	}
	return api.GetMedia200JSONResponse(media.DetailFromRow(rows[0], s.Store.PublicURL, canDelete(m, v))), nil
}

// canDelete: the uploader within seven days from the same browser, or a host.
func canDelete(m db.Medium, v viewer) bool {
	if v.isHost() {
		return true
	}
	return isUploader(m, v) && time.Since(m.CreatedAt) < deleteWindow
}

// DeleteMedia tombstones an item (state=removed) and tells open galleries.
func (s *Server) DeleteMedia(ctx context.Context, req api.DeleteMediaRequestObject) (api.DeleteMediaResponseObject, error) {
	m, err := s.mediaByID(ctx, req.MediaId)
	if err != nil {
		return nil, err
	}
	v, err := s.viewerForMedia(ctx, m)
	if err != nil {
		return nil, err
	}
	if !canDelete(m, v) {
		if v.p.Anonymous() {
			return nil, apperr.Unauthorizedf("")
		}
		return nil, apperr.Forbiddenf("only the uploader (within 7 days) or a host can remove this")
	}
	if err := s.Q.RemoveMedia(ctx, m.ID); err != nil {
		return nil, err
	}
	s.publishRemoved(m.EventID, m.ID)
	return api.DeleteMedia204Response{}, nil
}

// DownloadOriginal redirects to a five-minute presigned download of the original file.
func (s *Server) DownloadOriginal(ctx context.Context, req api.DownloadOriginalRequestObject) (api.DownloadOriginalResponseObject, error) {
	m, err := s.mediaByID(ctx, req.MediaId)
	if err != nil {
		return nil, err
	}
	v, err := s.viewerForMedia(ctx, m)
	if err != nil {
		return nil, err
	}
	if !v.canView() && !isUploader(m, v) {
		return nil, apperr.Forbiddenf("the host has closed this album")
	}
	if m.State == db.MediaStateUploading {
		return nil, apperr.Conflictf("upload not finished")
	}
	url, err := s.Store.PresignGet(ctx, m.OriginalKey, downloadName(m), 5*time.Minute)
	if err != nil {
		return nil, err
	}
	return redirectResponse{location: url}, nil
}

type redirectResponse struct{ location string }

func (r redirectResponse) VisitDownloadOriginalResponse(w http.ResponseWriter) error {
	w.Header().Set("Location", r.location)
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusFound)
	return nil
}

// downloadName is the filename offered for an original: the uploaded name or id + extension.
func downloadName(m db.Medium) string {
	if m.OriginalFilename != nil && *m.OriginalFilename != "" {
		return path.Base(strings.ReplaceAll(*m.OriginalFilename, "\\", "/"))
	}
	return ids.Encode(m.ID) + path.Ext(m.OriginalKey)
}

// RetryMedia re-queues a failed item. Hosts only.
func (s *Server) RetryMedia(ctx context.Context, req api.RetryMediaRequestObject) (api.RetryMediaResponseObject, error) {
	m, err := s.mediaByID(ctx, req.MediaId)
	if err != nil {
		return nil, err
	}
	v, err := s.viewerForMedia(ctx, m)
	if err != nil {
		return nil, err
	}
	if err := requireHost(v); err != nil {
		return nil, err
	}
	if m.State != db.MediaStateFailed {
		return nil, apperr.Conflictf("only failed items can be retried")
	}
	err = s.inTx(ctx, func(q *db.Queries) error {
		if err := q.SetMediaRequeued(ctx, m.ID); err != nil {
			return err
		}
		return jobs.EnqueueIngest(ctx, q, m.ID)
	})
	if err != nil {
		return nil, err
	}
	s.publishQueued(m.EventID, m.ID)
	return api.RetryMedia204Response{}, nil
}

// ListEventUploads is the host review: every uploader with their items and states.
func (s *Server) ListEventUploads(ctx context.Context, req api.ListEventUploadsRequestObject) (api.ListEventUploadsResponseObject, error) {
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
	rows, err := s.Q.ListHostUploads(ctx, row.Event.ID)
	if err != nil {
		return nil, err
	}
	status, err := s.eventStatus(ctx, row.Event.ID)
	if err != nil {
		return nil, err
	}

	// Rows arrive newest first; uploaders keep the order of their latest upload.
	index := map[string]int{}
	uploaders := []api.HostUploader{}
	for _, r := range rows {
		key := "u:" + string(r.UploaderUser)
		if r.UploaderUser == nil {
			key = "g:" + string(r.UploaderGuest)
		}
		i, ok := index[key]
		if !ok {
			i = len(uploaders)
			index[key] = i
			u := api.HostUploader{DisplayName: r.UploaderName, Items: []api.HostUploadItem{}}
			if r.UploaderGuest != nil {
				gid := ids.Encode(r.UploaderGuest)
				u.GuestId = &gid
			}
			if r.UploaderUser != nil && v.p.User != nil && string(r.UploaderUser) == string(v.p.User.ID) {
				u.IsYou = true
			}
			last := r.CreatedAt
			u.LastUploadAt = &last
			uploaders = append(uploaders, u)
		}
		u := &uploaders[i]
		u.Total++
		switch r.State {
		case db.MediaStateReady:
			u.Ready++
		case db.MediaStateFailed:
			u.Failed++
		}
		created := r.CreatedAt
		item := api.HostUploadItem{
			Id: ids.Encode(r.ID), Kind: api.HostUploadItemKind(r.Kind), State: api.HostUploadItemState(r.State),
			Error: r.Error, CreatedAt: &created, Name: r.OriginalFilename,
		}
		if r.OriginalBytes != nil {
			size := int(*r.OriginalBytes)
			item.Size = &size
		}
		if r.ThumbKey != "" {
			thumb := s.Store.PublicURL(r.ThumbKey)
			item.Thumb = &thumb
		}
		u.Items = append(u.Items, item)
	}
	return api.ListEventUploads200JSONResponse{Uploaders: uploaders, Status: status}, nil
}

// requireViewable loads a media item and checks the caller may see it (shared by likes).
func (s *Server) requireViewable(ctx context.Context, id string) (db.Medium, viewer, error) {
	m, err := s.mediaByID(ctx, id)
	if err != nil {
		return m, viewer{}, err
	}
	if m.State == db.MediaStateUploading || m.State == db.MediaStateFailed {
		return m, viewer{}, apperr.NotFoundf("media not found")
	}
	v, err := s.viewerForMedia(ctx, m)
	if err != nil {
		return m, v, err
	}
	if !v.canView() {
		return m, v, apperr.Forbiddenf("the host has closed this album")
	}
	return m, v, nil
}

var errNoRows = pgx.ErrNoRows

// isNoRows is a readable alias used in a few places.
func isNoRows(err error) bool { return errors.Is(err, errNoRows) }
