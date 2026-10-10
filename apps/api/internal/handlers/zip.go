package handlers

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"net/http"
	"path"
	"strings"
	"sync"
	"time"

	"yearbook/api/internal/apperr"
	"yearbook/api/internal/auth"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/storage"
)

// zipTickets is the in-memory store of authorised zip downloads (M1: no worker job, no temp files).
type zipTickets struct {
	mu      sync.Mutex
	ttl     time.Duration
	tickets map[string]zipTicket
}

type zipTicket struct {
	entries   []storage.ZipEntry
	expiresAt time.Time
}

func newZipTickets(ttl time.Duration) *zipTickets {
	return &zipTickets{ttl: ttl, tickets: map[string]zipTicket{}}
}

func (z *zipTickets) create(entries []storage.ZipEntry) (token string, expiresAt time.Time) {
	raw := make([]byte, 32)
	rand.Read(raw)
	token = base64.RawURLEncoding.EncodeToString(raw)
	expiresAt = time.Now().UTC().Add(z.ttl)
	z.mu.Lock()
	defer z.mu.Unlock()
	for k, t := range z.tickets {
		if time.Now().After(t.expiresAt) {
			delete(z.tickets, k)
		}
	}
	z.tickets[token] = zipTicket{entries: entries, expiresAt: expiresAt}
	return token, expiresAt
}

func (z *zipTickets) get(token string) ([]storage.ZipEntry, bool) {
	z.mu.Lock()
	defer z.mu.Unlock()
	t, ok := z.tickets[token]
	if !ok || time.Now().After(t.expiresAt) {
		return nil, false
	}
	return t.entries, true
}

// CreateZip authorises a selection and returns a short-lived download URL.
func (s *Server) CreateZip(ctx context.Context, req api.CreateZipRequestObject) (api.CreateZipResponseObject, error) {
	if req.Body == nil || len(req.Body.MediaIds) == 0 {
		return nil, apperr.BadRequestf("media_ids required")
	}
	originals := req.Body.Originals == nil || *req.Body.Originals
	ticket, err := s.zipTicket(ctx, req.Body.MediaIds, originals)
	if err != nil {
		return nil, err
	}
	return api.CreateZip200JSONResponse(ticket), nil
}

// zipTicket checks each item against the caller's permissions and issues a download ticket.
// Shared with the agent's export_zip tool.
func (s *Server) zipTicket(ctx context.Context, mediaIDs []api.Id, originals bool) (api.ZipTicket, error) {
	if len(mediaIDs) > 500 {
		return api.ZipTicket{}, apperr.BadRequestf("at most 500 items per zip")
	}
	idList := make([][]byte, 0, len(mediaIDs))
	for _, s := range mediaIDs {
		raw, err := ids.Decode(s)
		if err != nil {
			return api.ZipTicket{}, apperr.BadRequestf("invalid media id " + s)
		}
		idList = append(idList, raw)
	}
	rows, err := s.Q.ListMediaForZip(ctx, idList)
	if err != nil {
		return api.ZipTicket{}, err
	}

	// Permission is per event; cache the decision per event id. Library items are the owner's.
	// A share principal covers the shared album's items when the share allows downloads.
	p := auth.FromContext(ctx)
	allowed := map[string]bool{}
	entries := make([]storage.ZipEntry, 0, len(rows))
	names := map[string]int{}
	for _, r := range rows {
		key := string(r.EventID)
		ok, seen := allowed[key]
		if r.EventID == nil {
			ok, seen = p.User != nil && r.OwnerID != nil && string(r.OwnerID) == string(p.User.ID), true
		}
		if !seen {
			ev, err := s.Q.GetEventByID(ctx, r.EventID)
			if err != nil {
				return api.ZipTicket{}, err
			}
			v, err := s.viewerFor(ctx, ev.Event)
			if err != nil {
				return api.ZipTicket{}, err
			}
			ok = v.canView()
			allowed[key] = ok
		}
		if !ok && !s.sharedWith(ctx, viewer{p: p}, r.ID, true) {
			continue
		}
		entry, ok := zipEntryFor(r, originals, s.Store.Private, s.Store.Public)
		if !ok {
			continue
		}
		entry.Name = uniqueName(names, entry.Name)
		entries = append(entries, entry)
	}
	if len(entries) == 0 {
		return api.ZipTicket{}, apperr.NotFoundf("none of the items are available")
	}
	token, expiresAt := s.zips.create(entries)
	return api.ZipTicket{Url: "/api/v1/zips/" + token, ExpiresAt: expiresAt, Count: len(entries)}, nil
}

// zipEntryFor picks the original or the large variant for one row.
func zipEntryFor(r db.ListMediaForZipRow, originals bool, privateBucket, publicBucket string) (storage.ZipEntry, bool) {
	base := ids.Encode(r.ID)
	if r.OriginalFilename != nil && *r.OriginalFilename != "" {
		base = strings.TrimSuffix(path.Base(*r.OriginalFilename), path.Ext(*r.OriginalFilename))
	}
	if originals || r.Kind == "video" || r.LargeKey == "" {
		ext := path.Ext(r.OriginalKey)
		return storage.ZipEntry{Bucket: privateBucket, Key: r.OriginalKey, Name: base + ext}, true
	}
	return storage.ZipEntry{Bucket: publicBucket, Key: r.LargeKey, Name: base + ".webp"}, true
}

// uniqueName appends -2, -3, ... when two files would share a name inside the archive.
func uniqueName(seen map[string]int, name string) string {
	n := seen[name]
	seen[name] = n + 1
	if n == 0 {
		return name
	}
	ext := path.Ext(name)
	return fmt.Sprintf("%s-%d%s", strings.TrimSuffix(name, ext), n+1, ext)
}

// DownloadZip streams the archive for a ticket.
func (s *Server) DownloadZip(ctx context.Context, req api.DownloadZipRequestObject) (api.DownloadZipResponseObject, error) {
	entries, ok := s.zips.get(req.Token)
	if !ok {
		return nil, apperr.NotFoundf("this download link has expired")
	}
	return zipResponse{ctx: ctx, store: s.Store, entries: entries}, nil
}

type zipResponse struct {
	ctx     context.Context
	store   *storage.Client
	entries []storage.ZipEntry
}

func (r zipResponse) VisitDownloadZipResponse(w http.ResponseWriter) error {
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="yearbook-%s.zip"`, time.Now().Format("20060102-1504")))
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusOK)
	return r.store.StreamZip(r.ctx, w, r.entries)
}
