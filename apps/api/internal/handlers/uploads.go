package handlers

import (
	"context"
	"encoding/hex"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"

	"yearbook/api/internal/apperr"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/jobs"
	"yearbook/api/internal/media"
	"yearbook/api/internal/storage"
)

// Presigned URL lifetimes.
const (
	singlePutTTL = 15 * time.Minute
	multipartTTL = 6 * time.Hour
)

// CreateUploads validates up to 20 files and returns presigned single or multipart uploads.
// Files whose sha256 matches a ready item in the event come back as mode=duplicate.
func (s *Server) CreateUploads(ctx context.Context, req api.CreateUploadsRequestObject) (api.CreateUploadsResponseObject, error) {
	row, err := s.eventBySlug(ctx, req.Slug)
	if err != nil {
		return nil, err
	}
	v, err := s.viewerFor(ctx, row.Event)
	if err != nil {
		return nil, err
	}
	if !row.Event.GuestUpload && !v.isHost() {
		return nil, apperr.Forbiddenf("uploads are closed for this event")
	}
	if v.p.Anonymous() {
		return nil, apperr.Unauthorizedf("no identity; call POST /events/{slug}/guests first")
	}
	if req.Body == nil || len(req.Body.Files) == 0 {
		return nil, apperr.BadRequestf("files required")
	}
	if len(req.Body.Files) > media.MaxUploadsPerReq {
		return nil, apperr.BadRequestf(fmt.Sprintf("at most %d files per request", media.MaxUploadsPerReq))
	}

	// Validate everything before touching storage so one bad file fails the batch cleanly.
	type plan struct {
		file media.Kind
		ext  string
	}
	plans := make([]plan, len(req.Body.Files))
	for i, f := range req.Body.Files {
		kind, ext, ok := media.Classify(f.Type)
		details := map[string]any{"client_id": f.ClientId}
		if !ok {
			return nil, apperr.New(apperr.UnsupportedMedia, "unsupported file type "+f.Type).WithDetails(details)
		}
		if f.Size <= 0 {
			return nil, apperr.BadRequestf("size must be positive").WithDetails(details)
		}
		if int64(f.Size) > media.MaxBytes(kind) {
			return nil, apperr.New(apperr.TooLarge, fmt.Sprintf("%s files may be at most %d bytes", kind, media.MaxBytes(kind))).WithDetails(details)
		}
		plans[i] = plan{file: kind, ext: ext}
	}

	// A guest cookie needs its guests row in this event (the cookie is reused across events).
	guestID := v.guestID()
	if guestID == nil && v.p.CookieID != nil {
		g, err := s.ensureGuestRow(ctx, row.Event.ID, v.p.CookieID)
		if err != nil {
			return nil, err
		}
		guestID = g.ID
	}

	out := make([]api.UploadInit, 0, len(req.Body.Files))
	for i, f := range req.Body.Files {
		if f.Sha256 != nil {
			if dup, ok, err := s.findDuplicate(ctx, row.Event.ID, *f.Sha256); err != nil {
				return nil, err
			} else if ok {
				dupID := ids.Encode(dup)
				init := api.UploadInit{
					ClientId: f.ClientId, MediaId: dupID, Mode: api.UploadInitModeDuplicate, DuplicateOf: &dupID, ExpiresAt: time.Now().UTC(),
				}
				// Hand the client the existing item so it can show it without another request.
				if item, err := s.gridItem(ctx, dup, v); err == nil {
					init.Item = &item
				}
				out = append(out, init)
				continue
			}
		}
		init, err := s.createIntent(ctx, row.Event.ID, v, guestID, f, string(plans[i].file), plans[i].ext)
		if err != nil {
			return nil, err
		}
		out = append(out, init)
	}
	return api.CreateUploads200JSONResponse{Uploads: out}, nil
}

// findDuplicate looks for a ready item with the same content hash in the event.
func (s *Server) findDuplicate(ctx context.Context, eventID []byte, shaHex string) ([]byte, bool, error) {
	sum, err := hex.DecodeString(shaHex)
	if err != nil || len(sum) != 32 {
		return nil, false, nil // ignore malformed hashes; the worker computes the real one
	}
	id, err := s.Q.FindReadyDuplicate(ctx, db.FindReadyDuplicateParams{EventID: eventID, ContentSha256: sum})
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, false, nil
	}
	return id, err == nil, err
}

// createIntent inserts the media row in state uploading and presigns its upload.
func (s *Server) createIntent(ctx context.Context, eventID []byte, v viewer, guestID []byte, f api.UploadFile, kind, ext string) (api.UploadInit, error) {
	mediaID := ids.New()
	key := media.OriginalKey(ids.Encode(eventID), ids.Encode(mediaID), ext)
	size := int64(f.Size)
	init := api.UploadInit{ClientId: f.ClientId, MediaId: ids.Encode(mediaID)}
	var uploadID *string

	if size < media.SingleMaxBytes {
		put, err := s.Store.PresignPut(ctx, key, f.Type, singlePutTTL)
		if err != nil {
			return init, err
		}
		headers := put.Headers
		init.Mode, init.Url, init.Headers, init.ExpiresAt = api.UploadInitModeSingle, &put.URL, &headers, put.ExpiresAt
	} else {
		id, err := s.Store.CreateMultipart(ctx, key, f.Type)
		if err != nil {
			return init, err
		}
		uploadID = &id
		parts, err := s.presignParts(ctx, key, id, media.PartCount(size), nil)
		if err != nil {
			return init, err
		}
		partSize := media.PartSize
		init.Mode, init.Parts, init.PartSize, init.ExpiresAt = api.UploadInitModeMultipart, &parts, &partSize, time.Now().UTC().Add(multipartTTL)
	}

	name := f.Name
	_, err := s.Q.CreateMedia(ctx, db.CreateMediaParams{
		ID:                mediaID,
		EventID:           eventID,
		OwnerID:           v.p.UserID(),
		UploaderGuest:     guestID,
		UploaderUser:      v.p.UserID(),
		Kind:              kind,
		OriginalKey:       key,
		OriginalMime:      f.Type,
		OriginalFilename:  &name,
		ExpectedBytes:     &size,
		MultipartUploadID: uploadID,
		VariantPrefix:     ids.NewString(),
	})
	return init, err
}

// presignParts signs URLs for part numbers 1..total, skipping those already received.
func (s *Server) presignParts(ctx context.Context, key, uploadID string, total int, received map[int32]bool) ([]api.UploadPart, error) {
	parts := make([]api.UploadPart, 0, total)
	for n := 1; n <= total; n++ {
		if received[int32(n)] {
			continue
		}
		u, err := s.Store.PresignPart(ctx, key, uploadID, int32(n), multipartTTL)
		if err != nil {
			return nil, err
		}
		parts = append(parts, api.UploadPart{PartNumber: n, Url: u})
	}
	return parts, nil
}

// uploadForCaller loads an uploading media row and checks that the caller created it.
func (s *Server) uploadForCaller(ctx context.Context, id string) (db.Medium, viewer, error) {
	m, err := s.mediaByID(ctx, id)
	if err != nil {
		return m, viewer{}, err
	}
	v, err := s.viewerForMedia(ctx, m)
	if err != nil {
		return m, v, err
	}
	if !isUploader(m, v) {
		return m, v, apperr.Forbiddenf("not your upload")
	}
	return m, v, nil
}

// isUploader reports whether the viewer created the item (same user or same guest cookie).
func isUploader(m db.Medium, v viewer) bool {
	if m.UploaderUser != nil && v.p.User != nil && string(m.UploaderUser) == string(v.p.User.ID) {
		return true
	}
	return m.UploaderGuest != nil && v.guest != nil && string(m.UploaderGuest) == string(v.guest.ID)
}

// GetUploadStatus reports received parts and fresh URLs so a client can resume after a reload.
func (s *Server) GetUploadStatus(ctx context.Context, req api.GetUploadStatusRequestObject) (api.GetUploadStatusResponseObject, error) {
	m, _, err := s.uploadForCaller(ctx, req.MediaId)
	if err != nil {
		return nil, err
	}
	if m.State != db.MediaStateUploading {
		return nil, apperr.Conflictf("upload already completed")
	}
	status := api.UploadStatus{MediaId: ids.Encode(m.ID), ReceivedParts: []int{}, Parts: []api.UploadPart{}}
	if m.MultipartUploadID == nil {
		put, err := s.Store.PresignPut(ctx, m.OriginalKey, m.OriginalMime, singlePutTTL)
		if err != nil {
			return nil, err
		}
		status.Mode, status.Url, status.ExpiresAt = api.UploadStatusModeSingle, &put.URL, put.ExpiresAt
		return api.GetUploadStatus200JSONResponse(status), nil
	}
	received, err := s.Store.ListParts(ctx, m.OriginalKey, *m.MultipartUploadID)
	if err != nil {
		return nil, err
	}
	have := map[int32]bool{}
	for _, p := range received {
		have[p.Number] = true
		status.ReceivedParts = append(status.ReceivedParts, int(p.Number))
	}
	sort.Ints(status.ReceivedParts)
	var size int64
	if m.ExpectedBytes != nil {
		size = *m.ExpectedBytes
	}
	parts, err := s.presignParts(ctx, m.OriginalKey, *m.MultipartUploadID, media.PartCount(size), have)
	if err != nil {
		return nil, err
	}
	partSize := media.PartSize
	status.Mode, status.Parts, status.PartSize, status.ExpiresAt = api.UploadStatusModeMultipart, parts, &partSize, time.Now().UTC().Add(multipartTTL)
	return api.GetUploadStatus200JSONResponse(status), nil
}

// CompleteUpload verifies the object, queues the ingest job and returns the processing cell.
func (s *Server) CompleteUpload(ctx context.Context, req api.CompleteUploadRequestObject) (api.CompleteUploadResponseObject, error) {
	m, v, err := s.uploadForCaller(ctx, req.MediaId)
	if err != nil {
		return nil, err
	}
	switch m.State {
	case db.MediaStateUploading:
	case db.MediaStateQueued, db.MediaStateProcessing, db.MediaStateReady:
		item, err := s.gridItem(ctx, m.ID, v) // idempotent: a retried complete gets the same answer
		if err != nil {
			return nil, err
		}
		return api.CompleteUpload200JSONResponse(item), nil
	default:
		return nil, apperr.Conflictf("upload is in state " + string(m.State))
	}

	if m.MultipartUploadID != nil {
		var parts []storage.Part
		if req.Body != nil && req.Body.Parts != nil {
			for _, p := range *req.Body.Parts {
				parts = append(parts, storage.Part{Number: int32(p.PartNumber), ETag: p.Etag})
			}
		} else if parts, err = s.Store.ListParts(ctx, m.OriginalKey, *m.MultipartUploadID); err != nil {
			return nil, err
		}
		if len(parts) == 0 {
			return nil, apperr.Conflictf("no parts uploaded")
		}
		sort.Slice(parts, func(i, j int) bool { return parts[i].Number < parts[j].Number })
		if err := s.Store.CompleteMultipart(ctx, m.OriginalKey, *m.MultipartUploadID, parts); err != nil {
			return nil, apperr.Conflictf("could not assemble parts: " + err.Error())
		}
	}

	size, ok, err := s.Store.Head(ctx, s.Store.Private, m.OriginalKey)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, apperr.Conflictf("object not found in storage; upload it first")
	}
	if m.ExpectedBytes != nil && size != *m.ExpectedBytes {
		return nil, apperr.Conflictf(fmt.Sprintf("size mismatch: expected %d bytes, stored %d", *m.ExpectedBytes, size))
	}

	err = s.inTx(ctx, func(q *db.Queries) error {
		if err := q.SetMediaQueued(ctx, db.SetMediaQueuedParams{ID: m.ID, OriginalBytes: &size}); err != nil {
			return err
		}
		return jobs.EnqueueIngest(ctx, q, m.ID)
	})
	if err != nil {
		return nil, err
	}
	s.publishQueued(m.EventID, m.ID)
	item, err := s.gridItem(ctx, m.ID, v)
	if err != nil {
		return nil, err
	}
	return api.CompleteUpload200JSONResponse(item), nil
}

// AbortUpload discards an unfinished upload and its row.
func (s *Server) AbortUpload(ctx context.Context, req api.AbortUploadRequestObject) (api.AbortUploadResponseObject, error) {
	m, _, err := s.uploadForCaller(ctx, req.MediaId)
	if err != nil {
		return nil, err
	}
	if m.State != db.MediaStateUploading {
		return nil, apperr.Conflictf("upload already completed")
	}
	if m.MultipartUploadID != nil {
		logErr(ctx, "abort multipart", s.Store.AbortMultipart(ctx, m.OriginalKey, *m.MultipartUploadID))
	} else {
		logErr(ctx, "delete partial object", s.Store.Delete(ctx, s.Store.Private, m.OriginalKey))
	}
	if err := s.Q.DeleteMediaRow(ctx, m.ID); err != nil {
		return nil, err
	}
	return api.AbortUpload204Response{}, nil
}
