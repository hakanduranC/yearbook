// Package search turns a free-text query into one hybrid SQL statement: a SigLIP text embedding
// from the worker's ML server (vector candidates) fused with caption full text and trigram tags
// by reciprocal rank. When the embedder is unreachable the query degrades to text only.
package search

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/pgvector/pgvector-go"

	db "yearbook/api/internal/gen/db"
)

// Embedder returns the text-tower embedding of one query (1152-d, L2-normalized) or an error.
type Embedder interface {
	Embed(ctx context.Context, text string) ([]float32, error)
}

// EmbedTimeout bounds one call to the ML server; a slow embedder must not stall search.
const EmbedTimeout = 2 * time.Second

// HTTPEmbedder calls `POST {ML_URL}/embed/text` (docs/CONVENTIONS.md "ML server").
type HTTPEmbedder struct {
	URL    string
	Client *http.Client
}

// NewHTTPEmbedder builds an embedder for the ML server at baseURL.
func NewHTTPEmbedder(baseURL string) *HTTPEmbedder {
	return &HTTPEmbedder{URL: strings.TrimRight(baseURL, "/"), Client: &http.Client{Timeout: EmbedTimeout}}
}

// Embed posts the text and returns the first vector.
func (e *HTTPEmbedder) Embed(ctx context.Context, text string) ([]float32, error) {
	if e == nil || e.URL == "" {
		return nil, errors.New("search: no embedder configured")
	}
	ctx, cancel := context.WithTimeout(ctx, EmbedTimeout)
	defer cancel()
	body, _ := json.Marshal(map[string]any{"texts": []string{text}})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, e.URL+"/embed/text", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := e.Client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("search: embedder answered %d", resp.StatusCode)
	}
	var out struct {
		Vectors [][]float32 `json:"vectors"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if len(out.Vectors) == 0 || len(out.Vectors[0]) == 0 {
		return nil, errors.New("search: empty embedding")
	}
	return out.Vectors[0], nil
}

// Dim is the embedding width the media_embeddings column stores.
const Dim = 1152

// Scope is who is searching and what they may see.
type Scope struct {
	EventIDs       [][]byte // events the viewer may read
	IncludeLibrary bool     // also the viewer's own event-less items
	UserID         []byte
	GuestID        []byte // guests.id in the single event (for uploaded_by_me)
	IdentityID     []byte
	Actor          []byte
}

// Filters are the structured arguments of search_media (SDD §9). Zero values mean "no filter".
type Filters struct {
	Text          string
	Kind          string // photo | video
	From, To      *time.Time
	DayPart       string // morning | afternoon | evening | night
	PeopleAll     [][]byte
	PeopleAny     [][]byte
	PeopleExclude [][]byte
	Me            bool
	UploadedByMe  bool
	LikedByMe     bool
	FacesMin      *int
	FacesMax      *int
	MinScore      *float32
	Tags          []string
	AgeMin        *int
	AgeMax        *int
	AgeMode       string // exact | estimated | any
	IncludeDups   bool
	OrderBy       string // recent | best | oldest
	Limit         int
}

// Result is one hit, best first.
type Result struct {
	ID     []byte
	SortAt time.Time
	Score  float32
}

// Run executes the hybrid search. The embedder may be nil; its errors only log a warning.
func Run(ctx context.Context, q *db.Queries, emb Embedder, scope Scope, f Filters) ([]Result, error) {
	text := strings.TrimSpace(f.Text)
	var vec *pgvector.Vector
	if text != "" && emb != nil {
		v, err := emb.Embed(ctx, text)
		switch {
		case err != nil:
			slog.WarnContext(ctx, "search: embedder unavailable, text-only fallback", "err", err)
		case len(v) != Dim:
			slog.WarnContext(ctx, "search: embedder returned wrong width, text-only fallback", "dim", len(v))
		default:
			pv := pgvector.NewVector(v)
			vec = &pv
		}
	}
	limit := f.Limit
	if limit <= 0 {
		limit = 60
	}
	if limit > 200 {
		limit = 200
	}
	order := f.OrderBy
	if order == "" {
		order = "recent"
	}
	mode := f.AgeMode
	if mode == "" {
		mode = "any"
	}
	tags := make([]string, 0, len(f.Tags))
	for _, t := range f.Tags {
		if t = strings.ToLower(strings.TrimSpace(t)); t != "" {
			tags = append(tags, t)
		}
	}
	rows, err := q.SearchMedia(ctx, db.SearchMediaParams{
		EventIds: nonNil(scope.EventIDs), IncludeLibrary: scope.IncludeLibrary, UserID: scope.UserID,
		Q: text, QueryVec: vec, Kind: optString(f.Kind), FromAt: f.From, ToAt: f.To, DayPart: optString(f.DayPart),
		PeopleAll: nonNil(f.PeopleAll), PeopleAny: nonNil(f.PeopleAny), PeopleExclude: nonNil(f.PeopleExclude),
		Me: f.Me, IdentityID: scope.IdentityID, UploadedByMe: f.UploadedByMe, GuestID: scope.GuestID,
		LikedByMe: f.LikedByMe, Actor: scope.Actor, FacesMin: optInt32(f.FacesMin), FacesMax: optInt32(f.FacesMax),
		MinScore: f.MinScore, Tags: tags, AgeMin: optInt32(f.AgeMin), AgeMax: optInt32(f.AgeMax), AgeMode: mode,
		IncludeDups: f.IncludeDups, OrderBy: order, RowLimit: int32(limit),
	})
	if err != nil {
		return nil, err
	}
	out := make([]Result, 0, len(rows))
	for _, r := range rows {
		out = append(out, Result{ID: r.ID, SortAt: r.SortAt, Score: r.Score})
	}
	return out, nil
}

func nonNil(b [][]byte) [][]byte {
	if b == nil {
		return [][]byte{}
	}
	return b
}

func optString(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func optInt32(p *int) *int32 {
	if p == nil {
		return nil
	}
	v := int32(*p)
	return &v
}
