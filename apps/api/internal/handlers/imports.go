package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"yearbook/api/internal/apperr"
	"yearbook/api/internal/auth"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/jobs"
	"yearbook/api/internal/media"
	"yearbook/api/internal/storage"
)

// Imports: Takeout or zip archives go to the private bucket under imports/{id}.zip through the
// same presigned flow as media; folders are server paths for the operator. The light worker's
// `import` job does the rest (docs/CONVENTIONS.md "Import archives").

// MaxImportBytes bounds one archive (Takeout splits larger exports into several files).
const MaxImportBytes int64 = 50 << 30

// ImportKey is the private-bucket key of an archive.
func ImportKey(importID []byte) string { return "imports/" + ids.Encode(importID) + ".zip" }

func importJSON(i db.Import, slug *string) api.Import {
	out := api.Import{Id: ids.Encode(i.ID), Kind: api.ImportKind(i.Kind), State: api.ImportState(i.State), CreatedAt: i.CreatedAt, FinishedAt: i.FinishedAt, Error: i.Error, EventSlug: slug}
	var stats struct {
		Found, Imported, Duplicates, Failed, Matched int
		PeopleSeeded                                 *int `json:"people_seeded"`
	}
	_ = json.Unmarshal(i.Stats, &stats)
	out.Stats.Found, out.Stats.Imported, out.Stats.Duplicates, out.Stats.Failed, out.Stats.Matched = stats.Found, stats.Imported, stats.Duplicates, stats.Failed, stats.Matched
	out.Stats.PeopleSeeded = stats.PeopleSeeded
	return out
}

// importSlug resolves the event slug of an import row (nil when matching by time).
func (s *Server) importSlug(ctx context.Context, i db.Import) *string {
	if i.EventID == nil {
		return nil
	}
	ev, err := s.Q.GetEventByID(ctx, i.EventID)
	if err != nil {
		return nil
	}
	return &ev.Event.Slug
}

// ListImports lists the caller's imports, newest first.
func (s *Server) ListImports(ctx context.Context, _ api.ListImportsRequestObject) (api.ListImportsResponseObject, error) {
	user, err := requireUser(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := s.Q.ListImports(ctx, user.ID)
	if err != nil {
		return nil, err
	}
	out := api.ListImports200JSONResponse{Imports: make([]api.Import, 0, len(rows))}
	for _, r := range rows {
		out.Imports = append(out.Imports, importJSON(r, s.importSlug(ctx, r)))
	}
	return out, nil
}

// CreateImport starts an import: archives get presigned upload URLs, folders are queued at once.
func (s *Server) CreateImport(ctx context.Context, req api.CreateImportRequestObject) (api.CreateImportResponseObject, error) {
	user, err := requireUser(ctx)
	if err != nil {
		return nil, err
	}
	if req.Body == nil {
		return nil, apperr.BadRequestf("body required")
	}
	var eventID []byte
	var slug *string
	if req.Body.EventSlug != nil && *req.Body.EventSlug != "" {
		row, err := s.eventBySlug(ctx, *req.Body.EventSlug)
		if err != nil {
			return nil, err
		}
		v, err := s.viewerFor(ctx, row.Event)
		if err != nil {
			return nil, err
		}
		if !v.isHost() {
			return nil, apperr.Forbiddenf("only a host can import into this event")
		}
		eventID, slug = row.Event.ID, &row.Event.Slug
	}
	importID := ids.New()
	switch req.Body.Kind {
	case api.ImportCreateKindFolder:
		if s.Cfg.OperatorEmail == "" || !strings.EqualFold(user.Email, s.Cfg.OperatorEmail) {
			return nil, apperr.Forbiddenf("folder imports are for the operator")
		}
		if req.Body.Path == nil || !filepath.IsAbs(*req.Body.Path) {
			return nil, apperr.BadRequestf("path must be an absolute server directory")
		}
		imp, err := s.createImport(ctx, importID, user.ID, "folder", "queued", eventID, req.Body.Path, nil, nil)
		if err != nil {
			return nil, err
		}
		return api.CreateImport201JSONResponse(api.ImportInit(withUpload(importJSON(imp, slug), nil))), nil
	case api.ImportCreateKindTakeout, api.ImportCreateKindZip:
	default:
		return nil, apperr.BadRequestf("kind must be takeout, zip or folder")
	}
	if req.Body.Size == nil || *req.Body.Size <= 0 {
		return nil, apperr.BadRequestf("size required for archives")
	}
	size := int64(*req.Body.Size)
	if size > MaxImportBytes {
		return nil, apperr.New(apperr.TooLarge, fmt.Sprintf("archives may be at most %d bytes", MaxImportBytes))
	}
	key := ImportKey(importID)
	init := api.UploadInit{ClientId: "archive", MediaId: ids.Encode(importID)}
	var uploadID *string
	if size < media.SingleMaxBytes {
		put, err := s.Store.PresignPut(ctx, key, "application/zip", singlePutTTL)
		if err != nil {
			return nil, err
		}
		headers := put.Headers
		init.Mode, init.Url, init.Headers, init.ExpiresAt = api.UploadInitModeSingle, &put.URL, &headers, put.ExpiresAt
	} else {
		id, err := s.Store.CreateMultipart(ctx, key, "application/zip")
		if err != nil {
			return nil, err
		}
		uploadID = &id
		parts, err := s.presignParts(ctx, key, id, media.PartCount(size), nil)
		if err != nil {
			return nil, err
		}
		partSize := media.PartSize
		init.Mode, init.Parts, init.PartSize, init.ExpiresAt = api.UploadInitModeMultipart, &parts, &partSize, time.Now().UTC().Add(multipartTTL)
	}
	imp, err := s.createImport(ctx, importID, user.ID, string(req.Body.Kind), "uploading", eventID, &key, &size, uploadID)
	if err != nil {
		return nil, err
	}
	return api.CreateImport201JSONResponse(api.ImportInit(withUpload(importJSON(imp, slug), &init))), nil
}

func (s *Server) createImport(ctx context.Context, id, owner []byte, kind, state string, eventID []byte, source *string, size *int64, uploadID *string) (db.Import, error) {
	var imp db.Import
	err := s.inTx(ctx, func(q *db.Queries) error {
		var err error
		imp, err = q.CreateImport(ctx, db.CreateImportParams{ID: id, OwnerID: owner, Kind: kind, State: state, EventID: eventID, SourceKey: source, SourceBytes: size, MultipartUploadID: uploadID})
		if err != nil {
			return err
		}
		if state == "queued" {
			return jobs.EnqueueImport(ctx, q, id)
		}
		return nil
	})
	return imp, err
}

// withUpload builds the ImportInit shape (Import plus the optional upload).
func withUpload(i api.Import, up *api.UploadInit) api.ImportInit {
	out := api.ImportInit{Id: i.Id, Kind: api.ImportInitKind(i.Kind), State: api.ImportInitState(i.State), CreatedAt: i.CreatedAt, FinishedAt: i.FinishedAt, Error: i.Error, EventSlug: i.EventSlug, Upload: up}
	out.Stats.Found, out.Stats.Imported, out.Stats.Duplicates, out.Stats.Failed, out.Stats.Matched, out.Stats.PeopleSeeded =
		i.Stats.Found, i.Stats.Imported, i.Stats.Duplicates, i.Stats.Failed, i.Stats.Matched, i.Stats.PeopleSeeded
	return out
}

// importForCaller loads an import owned by the signed-in user.
func (s *Server) importForCaller(ctx context.Context, id string) (db.Import, error) {
	user, err := requireUser(ctx)
	if err != nil {
		return db.Import{}, err
	}
	raw, err := ids.Decode(id)
	if err != nil {
		return db.Import{}, apperr.NotFoundf("import not found")
	}
	imp, err := s.Q.GetImport(ctx, raw)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && string(imp.OwnerID) != string(user.ID)) {
		return db.Import{}, apperr.NotFoundf("import not found")
	}
	return imp, err
}

// GetImport returns the state and stats (the web app polls this while running).
func (s *Server) GetImport(ctx context.Context, req api.GetImportRequestObject) (api.GetImportResponseObject, error) {
	imp, err := s.importForCaller(ctx, req.ImportId)
	if err != nil {
		return nil, err
	}
	return api.GetImport200JSONResponse(importJSON(imp, s.importSlug(ctx, imp))), nil
}

// CancelImport cancels an import the worker has not started; running ones cannot be stopped.
func (s *Server) CancelImport(ctx context.Context, req api.CancelImportRequestObject) (api.CancelImportResponseObject, error) {
	imp, err := s.importForCaller(ctx, req.ImportId)
	if err != nil {
		return nil, err
	}
	err = s.inTx(ctx, func(q *db.Queries) error {
		n, err := q.CancelImport(ctx, imp.ID)
		if err != nil {
			return err
		}
		if n == 0 {
			return apperr.Conflictf("import is " + imp.State + " and cannot be cancelled")
		}
		return q.DeleteOpenImportJob(ctx, ids.Encode(imp.ID))
	})
	if err != nil {
		return nil, err
	}
	if imp.State == "uploading" && imp.SourceKey != nil {
		if imp.MultipartUploadID != nil {
			logErr(ctx, "abort import multipart", s.Store.AbortMultipart(ctx, *imp.SourceKey, *imp.MultipartUploadID))
		} else {
			logErr(ctx, "delete import object", s.Store.Delete(ctx, s.Store.Private, *imp.SourceKey))
		}
	}
	return api.CancelImport204Response{}, nil
}

// CompleteImport verifies the archive in storage and queues the import job.
func (s *Server) CompleteImport(ctx context.Context, req api.CompleteImportRequestObject) (api.CompleteImportResponseObject, error) {
	imp, err := s.importForCaller(ctx, req.ImportId)
	if err != nil {
		return nil, err
	}
	switch imp.State {
	case "uploading":
	case "queued", "running", "done":
		return api.CompleteImport200JSONResponse(importJSON(imp, s.importSlug(ctx, imp))), nil
	default:
		return nil, apperr.Conflictf("import is " + imp.State)
	}
	if imp.SourceKey == nil {
		return nil, apperr.Conflictf("import has no archive")
	}
	if imp.MultipartUploadID != nil {
		var parts []storage.Part
		if req.Body != nil && req.Body.Parts != nil {
			for _, p := range *req.Body.Parts {
				parts = append(parts, storage.Part{Number: int32(p.PartNumber), ETag: p.Etag})
			}
		} else if parts, err = s.Store.ListParts(ctx, *imp.SourceKey, *imp.MultipartUploadID); err != nil {
			return nil, err
		}
		if len(parts) == 0 {
			return nil, apperr.Conflictf("no parts uploaded")
		}
		sort.Slice(parts, func(i, j int) bool { return parts[i].Number < parts[j].Number })
		if err := s.Store.CompleteMultipart(ctx, *imp.SourceKey, *imp.MultipartUploadID, parts); err != nil {
			return nil, apperr.Conflictf("could not assemble parts: " + err.Error())
		}
	}
	size, ok, err := s.Store.Head(ctx, s.Store.Private, *imp.SourceKey)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, apperr.Conflictf("archive not found in storage; upload it first")
	}
	if imp.SourceBytes != nil && size != *imp.SourceBytes {
		return nil, apperr.Conflictf(fmt.Sprintf("size mismatch: expected %d bytes, stored %d", *imp.SourceBytes, size))
	}
	err = s.inTx(ctx, func(q *db.Queries) error {
		if err := q.SetImportQueued(ctx, db.SetImportQueuedParams{ID: imp.ID, SourceBytes: &size}); err != nil {
			return err
		}
		return jobs.EnqueueImport(ctx, q, imp.ID)
	})
	if err != nil {
		return nil, err
	}
	imp, err = s.Q.GetImport(ctx, imp.ID)
	if err != nil {
		return nil, err
	}
	return api.CompleteImport200JSONResponse(importJSON(imp, s.importSlug(ctx, imp))), nil
}

// ListMyLibrary pages the user's own media (imports and uploads), optionally only unassigned.
func (s *Server) ListMyLibrary(ctx context.Context, req api.ListMyLibraryRequestObject) (api.ListMyLibraryResponseObject, error) {
	user, err := requireUser(ctx)
	if err != nil {
		return nil, err
	}
	identity, err := s.identityFor(ctx, auth.FromContext(ctx))
	if err != nil {
		return nil, err
	}
	v := viewer{p: auth.FromContext(ctx), identity: identity, library: true, role: api.ViewerRoleOwner}
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
	rows, err := s.Q.ListLibraryIDs(ctx, db.ListLibraryIDsParams{
		OwnerID: user.ID, Unassigned: req.Params.Unassigned != nil && *req.Params.Unassigned,
		CursorID: cursor.ID, CursorAt: cursor.At, RowLimit: int32(limit + 1),
	})
	if err != nil {
		return nil, err
	}
	var idList [][]byte
	var times []time.Time
	for _, r := range rows {
		idList, times = append(idList, r.ID), append(times, r.SortAt)
	}
	var next *string
	if len(idList) > limit {
		enc := media.Cursor{At: times[limit-1], ID: idList[limit-1]}.Encode(false)
		next = &enc
		idList, times = idList[:limit], times[:limit]
	}
	page, err := s.buildPage(ctx, idList, times, v, time.UTC)
	if err != nil {
		return nil, err
	}
	page.NextCursor = next
	return api.ListMyLibrary200JSONResponse(page), nil
}

// AssignMediaEvent moves one of my items into one of my events (or back to the library with
// event_slug null). Faces follow the item; a recluster is queued for the affected events.
func (s *Server) AssignMediaEvent(ctx context.Context, req api.AssignMediaEventRequestObject) (api.AssignMediaEventResponseObject, error) {
	user, err := requireUser(ctx)
	if err != nil {
		return nil, err
	}
	if req.Body == nil {
		return nil, apperr.BadRequestf("body required")
	}
	raw, err := ids.Decode(req.MediaId)
	if err != nil {
		return nil, apperr.NotFoundf("media not found")
	}
	m, err := s.Q.GetMediaForOwner(ctx, db.GetMediaForOwnerParams{ID: raw, OwnerID: user.ID})
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, apperr.NotFoundf("media not found")
	}
	if err != nil {
		return nil, err
	}
	var target []byte
	var targetEvent *db.Event
	if req.Body.EventSlug != nil && *req.Body.EventSlug != "" {
		row, err := s.eventBySlug(ctx, *req.Body.EventSlug)
		if err != nil {
			return nil, err
		}
		v, err := s.viewerFor(ctx, row.Event)
		if err != nil {
			return nil, err
		}
		if !v.isHost() {
			return nil, apperr.Forbiddenf("only a host can move items into this event")
		}
		target, targetEvent = row.Event.ID, &row.Event
	}
	err = s.inTx(ctx, func(q *db.Queries) error {
		if err := q.SetMediaEvent(ctx, db.SetMediaEventParams{ID: m.ID, EventID: target}); err != nil {
			return err
		}
		if err := q.SetFacesEvent(ctx, db.SetFacesEventParams{MediaID: m.ID, EventID: target}); err != nil {
			return err
		}
		for _, e := range [][]byte{m.EventID, target} {
			if err := jobs.EnqueueClusterEvent(ctx, q, e); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	if m.EventID != nil {
		s.publishRemoved(m.EventID, m.ID)
	}
	if targetEvent != nil {
		s.publishQueued(target, m.ID)
	}
	v := viewer{p: auth.FromContext(ctx), role: api.ViewerRoleOwner, library: true}
	if targetEvent != nil {
		v, err = s.viewerFor(ctx, *targetEvent)
		if err != nil {
			return nil, err
		}
	}
	item, err := s.gridItem(ctx, m.ID, v)
	if err != nil {
		return nil, err
	}
	return api.AssignMediaEvent200JSONResponse(item), nil
}
