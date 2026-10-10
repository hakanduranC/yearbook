package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"yearbook/api/internal/agent"
	"yearbook/api/internal/apperr"
	"yearbook/api/internal/auth"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/search"
)

// Agent tools (SDD §9 layer 1). They are plain Go functions bound to a toolScope; the MCP server
// at /mcp and the saved-command runner call them. Every result carries ids, counts, names,
// timestamps, captions and scores only: no crops, embeddings, emails, birthdates or GPS.

// toolScope is the caller plus the optional event the tools are scoped to.
type toolScope struct {
	p        auth.Principal
	identity *db.Identity
	ev       *db.GetEventBySlugRow // nil = every event the caller can see plus their library
	v        viewer                // the viewer in ev, or a cross-event viewer
	eventIDs [][]byte
}

// toolScopeFor resolves principal p (and eventSlug, if given) into a toolScope.
func (s *Server) toolScopeFor(ctx context.Context, p auth.Principal, eventSlug string) (toolScope, error) {
	if p.Anonymous() {
		return toolScope{}, apperr.Unauthorizedf("sign in or open an event as a guest first")
	}
	identity, err := s.identityFor(ctx, p)
	if err != nil {
		return toolScope{}, err
	}
	sc := toolScope{p: p, identity: identity, v: viewer{p: p, identity: identity, library: true}}
	if eventSlug != "" {
		row, err := s.eventBySlug(ctx, eventSlug)
		if err != nil {
			return toolScope{}, err
		}
		v, err := s.viewerFor(auth.WithPrincipal(ctx, p), row.Event)
		if err != nil {
			return toolScope{}, err
		}
		if !v.canView() {
			return toolScope{}, apperr.Forbiddenf("the host has closed this album")
		}
		sc.ev, sc.v, sc.eventIDs = &row, v, [][]byte{row.Event.ID}
		return sc, nil
	}
	sc.eventIDs, err = s.Q.ListVisibleEventIDs(ctx, db.ListVisibleEventIDsParams{UserID: p.UserID(), CookieID: p.CookieID})
	if err != nil {
		return toolScope{}, err
	}
	return sc, nil
}

func (sc toolScope) searchScope() search.Scope {
	return search.Scope{
		EventIDs: sc.eventIDs, IncludeLibrary: sc.ev == nil && sc.p.User != nil,
		UserID: sc.p.UserID(), GuestID: sc.v.guestID(), IdentityID: sc.v.identityID(), Actor: sc.p.Actor(),
	}
}

// eventID is the scoped event id or nil.
func (sc toolScope) eventID() []byte {
	if sc.ev == nil {
		return nil
	}
	return sc.ev.Event.ID
}

// toolSpec is one tool: its JSON schema and implementation.
type toolSpec struct {
	Name        string
	Description string
	Schema      map[string]any
	Call        func(ctx context.Context, sc toolScope, args json.RawMessage) (any, error)
}

func obj(props map[string]any, required ...string) map[string]any {
	m := map[string]any{"type": "object", "properties": props, "additionalProperties": false}
	if len(required) > 0 {
		m["required"] = required
	}
	return m
}

func str(desc string) map[string]any   { return map[string]any{"type": "string", "description": desc} }
func num(desc string) map[string]any   { return map[string]any{"type": "integer", "description": desc} }
func boolT(desc string) map[string]any { return map[string]any{"type": "boolean", "description": desc} }
func strList(desc string) map[string]any {
	return map[string]any{"type": "array", "items": map[string]any{"type": "string"}, "description": desc}
}

// searchArgs are the arguments of search_media (SDD §9).
type searchArgs struct {
	Text          string   `json:"text"`
	PeopleAll     []string `json:"people_all"`
	PeopleAny     []string `json:"people_any"`
	PeopleExclude []string `json:"people_exclude"`
	Me            bool     `json:"me"`
	From          string   `json:"from"`
	To            string   `json:"to"`
	DayPart       string   `json:"day_part"`
	Kind          string   `json:"kind"`
	UploadedByMe  bool     `json:"uploaded_by_me"`
	LikedByMe     bool     `json:"liked_by_me"`
	FacesMin      *int     `json:"faces_min"`
	FacesMax      *int     `json:"faces_max"`
	MinScore      *float32 `json:"min_score"`
	Tags          []string `json:"tags"`
	AgeMin        *int     `json:"age_min"`
	AgeMax        *int     `json:"age_max"`
	AgeMode       string   `json:"age_mode"`
	Order         string   `json:"order"`
	Limit         int      `json:"limit"`
	EventSlug     string   `json:"event_slug"`
}

var searchSchema = obj(map[string]any{
	"text":           str("What is visible in the picture (cake, dancing, outdoors). Hybrid vector + text search. Leave empty to filter only."),
	"people_all":     strList("Person ids that must all appear"),
	"people_any":     strList("Person ids of which at least one appears"),
	"people_exclude": strList("Person ids that must not appear"),
	"me":             boolT("Only photos the caller appears in (needs a claimed person)"),
	"from":           str("RFC 3339 lower bound of the capture time"),
	"to":             str("RFC 3339 upper bound (exclusive)"),
	"day_part":       map[string]any{"type": "string", "enum": []string{"morning", "afternoon", "evening", "night"}},
	"kind":           map[string]any{"type": "string", "enum": []string{"photo", "video"}},
	"uploaded_by_me": boolT("Only the caller's own uploads"),
	"liked_by_me":    boolT("Only items the caller liked"),
	"faces_min":      num("Minimum number of faces"),
	"faces_max":      num("Maximum number of faces"),
	"min_score":      map[string]any{"type": "number", "description": "Minimum quality score 0..1"},
	"tags":           strList("Tags from the tagger, any match"),
	"age_min":        num("Minimum age of at least one person in the photo"),
	"age_max":        num("Maximum age of at least one person in the photo"),
	"age_mode":       map[string]any{"type": "string", "enum": []string{"exact", "estimated", "any"}, "description": "exact uses linked birthdates, estimated the face estimate, any both"},
	"order":          map[string]any{"type": "string", "enum": []string{"recent", "best", "oldest"}},
	"limit":          num("1..200, default 60"),
	"event_slug":     str("Restrict to one event when the scope is all events"),
})

// toolSpecs returns the fixed tool set.
func (s *Server) toolSpecs() []toolSpec {
	return []toolSpec{
		{
			Name:        "resolve_people",
			Description: "Find person ids by (partial) name in the caller's events. Call before search_media when the user names someone.",
			Schema:      obj(map[string]any{"name": str("The name as the user wrote it")}, "name"),
			Call:        s.toolResolvePeople,
		},
		{
			Name:        "search_media",
			Description: "Search photos and videos with free text and structured filters. Returns media ids best match first.",
			Schema:      searchSchema,
			Call:        s.toolSearchMedia,
		},
		{
			Name:        "rank_best",
			Description: "Order the given media ids by quality score, or return the event's highlights when no ids are given.",
			Schema:      obj(map[string]any{"media_ids": strList("Ids to rank"), "limit": num("Default 24, max 100")}),
			Call:        s.toolRankBest,
		},
		{
			Name:        "list_people",
			Description: "List the persons (face clusters) of the scoped events, biggest first.",
			Schema:      obj(map[string]any{"event_slug": str("One event; default: the scope")}),
			Call:        s.toolListPeople,
		},
		{
			Name:        "describe_media",
			Description: "Metadata of one item: time, uploader, likes, score, persons, tags, caption. No pixels.",
			Schema:      obj(map[string]any{"media_id": str("Media id")}, "media_id"),
			Call:        s.toolDescribeMedia,
		},
		{
			Name:        "create_album",
			Description: "Create an album from media ids. Returns the album id.",
			Schema:      obj(map[string]any{"title": str("1-120 characters"), "media_ids": strList("Items in order"), "event_slug": str("Event of the album; default: the scope")}, "title", "media_ids"),
			Call:        s.toolCreateAlbum,
		},
		{
			Name:        "like_media",
			Description: "Like items on behalf of the caller (idempotent).",
			Schema:      obj(map[string]any{"media_ids": strList("Up to 50 ids")}, "media_ids"),
			Call:        s.toolLikeMedia,
		},
		{
			Name:        "share_album",
			Description: "Create a read-only share link for an album the caller may edit.",
			Schema:      obj(map[string]any{"album_id": str("Album id"), "expires_days": num("1..365"), "allow_download": boolT("Default true")}, "album_id"),
			Call:        s.toolShareAlbum,
		},
		{
			Name:        "export_zip",
			Description: "Prepare a zip download of media ids. Returns a URL valid for 10 minutes.",
			Schema:      obj(map[string]any{"media_ids": strList("Up to 500 ids"), "originals": boolT("Originals (default) or large variants")}, "media_ids"),
			Call:        s.toolExportZip,
		},
		{
			Name:        "event_stats",
			Description: "Counters of the scoped events: photos, videos, processing, people, photos of the caller.",
			Schema:      obj(map[string]any{"event_slug": str("One event; default: the scope")}),
			Call:        s.toolEventStats,
		},
		{
			Name: "run_query",
			Description: "Run one read-only SELECT over the views v_events, v_media, v_persons, v_faces, v_tags, v_likes, " +
				"already filtered to what the caller may see. Booleans is_me, by_me, uploaded_by_me. 2 s timeout, 500 rows max. " +
				"Errors come back verbatim: fix the SQL and retry (max 2 retries).",
			Schema: obj(map[string]any{"sql": str("One SELECT statement")}, "sql"),
			Call:   s.toolRunQuery,
		},
		{
			Name:        "run_saved_command",
			Description: "Run a saved command (chip) by id with bind parameters, without a model call.",
			Schema:      obj(map[string]any{"command_id": str("Saved command id"), "params": map[string]any{"type": "object", "additionalProperties": true}}, "command_id"),
			Call:        s.toolRunSavedCommand,
		},
	}
}

// callTool runs one tool by name with the principal placed on the context.
func (s *Server) callTool(ctx context.Context, sc toolScope, name string, args json.RawMessage) (any, error) {
	for _, t := range s.toolSpecs() {
		if t.Name == name {
			if len(args) == 0 {
				args = json.RawMessage("{}")
			}
			return t.Call(auth.WithPrincipal(ctx, sc.p), sc, args)
		}
	}
	return nil, fmt.Errorf("unknown tool %q", name)
}

func decodeArgs(args json.RawMessage, into any) error {
	if len(args) == 0 {
		return nil
	}
	if err := json.Unmarshal(args, into); err != nil {
		return fmt.Errorf("invalid arguments: %v", err)
	}
	return nil
}

// decodeIDs decodes 22-char ids, skipping malformed ones.
func decodeIDs(list []string) [][]byte {
	out := make([][]byte, 0, len(list))
	for _, s := range list {
		if raw, err := ids.Decode(s); err == nil {
			out = append(out, raw)
		}
	}
	return out
}

// scopeForSlug narrows sc to one event when the tool names one (must be inside the scope).
func (s *Server) scopeForSlug(ctx context.Context, sc toolScope, slug string) (toolScope, error) {
	if slug == "" || (sc.ev != nil && sc.ev.Event.Slug == slug) {
		return sc, nil
	}
	if sc.ev != nil {
		return sc, fmt.Errorf("event %q is outside the current scope", slug)
	}
	return s.toolScopeFor(ctx, sc.p, slug)
}

// personSummary is the public shape of a person in tool results.
type personSummary struct {
	PersonID    string `json:"person_id"`
	DisplayName string `json:"display_name,omitempty"`
	EventSlug   string `json:"event_slug"`
	FaceCount   int    `json:"face_count"`
	IsMe        bool   `json:"is_me"`
}

func (s *Server) toolResolvePeople(ctx context.Context, sc toolScope, args json.RawMessage) (any, error) {
	var in struct {
		Name string `json:"name"`
	}
	if err := decodeArgs(args, &in); err != nil {
		return nil, err
	}
	in.Name = strings.TrimSpace(in.Name)
	if in.Name == "" {
		return nil, errors.New("name is required")
	}
	rows, err := s.Q.SearchPersonsByName(ctx, db.SearchPersonsByNameParams{EventIds: sc.eventIDs, Q: in.Name})
	if err != nil {
		return nil, err
	}
	out := []personSummary{}
	for _, r := range rows {
		name := ""
		if r.DisplayName != nil {
			name = *r.DisplayName
		}
		isMe := false
		if sc.identity != nil {
			if l, err := s.Q.GetPersonLink(ctx, r.ID); err == nil {
				isMe = string(l.IdentityID) == string(sc.identity.ID)
			}
		}
		out = append(out, personSummary{PersonID: ids.Encode(r.ID), DisplayName: name, EventSlug: r.EventSlug, FaceCount: int(r.FaceCount), IsMe: isMe})
	}
	return map[string]any{"persons": out, "count": len(out)}, nil
}

// mediaSummary is the per-item metadata in tool results.
type mediaSummary struct {
	ID         string     `json:"id"`
	Kind       string     `json:"kind"`
	CapturedAt *time.Time `json:"captured_at"`
	LikeCount  int        `json:"like_count"`
	Score      *float32   `json:"score,omitempty"`
	PersonIDs  []string   `json:"person_ids"`
	Me         bool       `json:"me"`
}

func summaries(rows []db.GetGridRowsRow) []mediaSummary {
	out := make([]mediaSummary, 0, len(rows))
	for _, r := range rows {
		m := mediaSummary{ID: ids.Encode(r.ID), Kind: r.Kind, CapturedAt: r.CapturedAt, LikeCount: int(r.LikeCount), Score: r.Score, Me: r.Me, PersonIDs: []string{}}
		for _, pid := range r.PersonIds {
			m.PersonIDs = append(m.PersonIDs, ids.Encode(pid))
		}
		out = append(out, m)
	}
	return out
}

// runSearch executes search_media arguments for a scope and returns the ids (best first).
func (s *Server) runSearch(ctx context.Context, sc toolScope, in searchArgs) ([][]byte, error) {
	sc, err := s.scopeForSlug(ctx, sc, in.EventSlug)
	if err != nil {
		return nil, err
	}
	f := search.Filters{
		Text: in.Text, Kind: in.Kind, DayPart: in.DayPart, Me: in.Me, UploadedByMe: in.UploadedByMe, LikedByMe: in.LikedByMe,
		FacesMin: in.FacesMin, FacesMax: in.FacesMax, MinScore: in.MinScore, Tags: in.Tags, AgeMin: in.AgeMin, AgeMax: in.AgeMax,
		AgeMode: in.AgeMode, OrderBy: in.Order, Limit: in.Limit,
		PeopleAll: decodeIDs(in.PeopleAll), PeopleAny: decodeIDs(in.PeopleAny), PeopleExclude: decodeIDs(in.PeopleExclude),
	}
	if in.Me && sc.identity == nil {
		return nil, errors.New("the caller has not claimed a person yet; me cannot be used")
	}
	for _, p := range []struct {
		s string
		t **time.Time
	}{{in.From, &f.From}, {in.To, &f.To}} {
		if p.s == "" {
			continue
		}
		ts, err := time.Parse(time.RFC3339, p.s)
		if err != nil {
			if ts, err = time.Parse("2006-01-02", p.s); err != nil {
				return nil, fmt.Errorf("from/to must be RFC 3339 or YYYY-MM-DD, got %q", p.s)
			}
		}
		*p.t = &ts
	}
	results, err := search.Run(ctx, s.Q, s.Embedder, sc.searchScope(), f)
	if err != nil {
		return nil, err
	}
	out := make([][]byte, 0, len(results))
	for _, r := range results {
		out = append(out, r.ID)
	}
	return out, nil
}

func (s *Server) toolSearchMedia(ctx context.Context, sc toolScope, args json.RawMessage) (any, error) {
	var in searchArgs
	if err := decodeArgs(args, &in); err != nil {
		return nil, err
	}
	idList, err := s.runSearch(ctx, sc, in)
	if err != nil {
		return nil, err
	}
	return s.mediaToolResult(ctx, sc, idList)
}

// mediaToolResult is the common shape: all ids plus metadata for the first 30.
func (s *Server) mediaToolResult(ctx context.Context, sc toolScope, idList [][]byte) (any, error) {
	encoded := make([]string, 0, len(idList))
	for _, id := range idList {
		encoded = append(encoded, ids.Encode(id))
	}
	sample := idList
	if len(sample) > 30 {
		sample = sample[:30]
	}
	rows, err := s.gridRows(ctx, sample, sc.v)
	if err != nil {
		return nil, err
	}
	return map[string]any{"count": len(encoded), "media_ids": encoded, "items": summaries(rows)}, nil
}

func (s *Server) toolRankBest(ctx context.Context, sc toolScope, args json.RawMessage) (any, error) {
	var in struct {
		MediaIDs []string `json:"media_ids"`
		Limit    int      `json:"limit"`
	}
	if err := decodeArgs(args, &in); err != nil {
		return nil, err
	}
	limit := in.Limit
	if limit <= 0 {
		limit = 24
	}
	limit = min(limit, 100)
	if len(in.MediaIDs) == 0 {
		if sc.ev == nil {
			return nil, errors.New("give media_ids, or scope the call to one event for its highlights")
		}
		rows, err := s.Q.ListMediaIDsBest(ctx, db.ListMediaIDsBestParams{EventID: sc.ev.Event.ID, RowLimit: int32(limit), CursorScore: -1})
		if err != nil {
			return nil, err
		}
		idList := make([][]byte, 0, len(rows))
		for _, r := range rows {
			idList = append(idList, r.ID)
		}
		return s.mediaToolResult(ctx, sc, idList)
	}
	visible, err := s.visibleMedia(ctx, sc, decodeIDs(in.MediaIDs))
	if err != nil {
		return nil, err
	}
	rows, err := s.gridRows(ctx, visible, sc.v)
	if err != nil {
		return nil, err
	}
	sort.SliceStable(rows, func(i, j int) bool {
		si, sj := float32(-1), float32(-1)
		if rows[i].Score != nil {
			si = *rows[i].Score
		}
		if rows[j].Score != nil {
			sj = *rows[j].Score
		}
		return si > sj
	})
	if len(rows) > limit {
		rows = rows[:limit]
	}
	idList := make([][]byte, 0, len(rows))
	for _, r := range rows {
		idList = append(idList, r.ID)
	}
	return s.mediaToolResult(ctx, sc, idList)
}

// visibleMedia keeps the ids the scope may see: in a scoped event, or the caller's own library.
func (s *Server) visibleMedia(ctx context.Context, sc toolScope, idList [][]byte) ([][]byte, error) {
	if len(idList) == 0 {
		return nil, nil
	}
	rows, err := s.Q.ListMediaByIDs(ctx, idList)
	if err != nil {
		return nil, err
	}
	allowed := map[string]bool{}
	for _, e := range sc.eventIDs {
		allowed[string(e)] = true
	}
	ok := map[string]bool{}
	for _, m := range rows {
		if m.State == db.MediaStateRemoved || m.State == db.MediaStateUploading {
			continue
		}
		if (m.EventID != nil && allowed[string(m.EventID)]) || (m.EventID == nil && sc.p.User != nil && m.OwnerID != nil && string(m.OwnerID) == string(sc.p.User.ID)) {
			ok[string(m.ID)] = true
		}
	}
	out := make([][]byte, 0, len(idList))
	for _, id := range idList {
		if ok[string(id)] {
			out = append(out, id)
		}
	}
	return out, nil
}

func (s *Server) toolListPeople(ctx context.Context, sc toolScope, args json.RawMessage) (any, error) {
	var in struct {
		EventSlug string `json:"event_slug"`
	}
	if err := decodeArgs(args, &in); err != nil {
		return nil, err
	}
	sc, err := s.scopeForSlug(ctx, sc, in.EventSlug)
	if err != nil {
		return nil, err
	}
	out := []personSummary{}
	events := sc.eventIDs
	if len(events) > 20 {
		events = events[:20]
	}
	for _, eid := range events {
		ev, err := s.Q.GetEventByID(ctx, eid)
		if err != nil {
			continue
		}
		persons, err := s.Q.ListPersons(ctx, db.ListPersonsParams{EventID: eid, IdentityID: sc.v.identityID()})
		if err != nil {
			return nil, err
		}
		for i, p := range persons {
			if i >= 50 {
				break
			}
			name := ""
			if p.DisplayName != nil {
				name = *p.DisplayName
			}
			out = append(out, personSummary{PersonID: ids.Encode(p.ID), DisplayName: name, EventSlug: ev.Event.Slug, FaceCount: int(p.FaceCount), IsMe: p.IsMe})
		}
	}
	return map[string]any{"persons": out, "count": len(out)}, nil
}

func (s *Server) toolDescribeMedia(ctx context.Context, sc toolScope, args json.RawMessage) (any, error) {
	var in struct {
		MediaID string `json:"media_id"`
	}
	if err := decodeArgs(args, &in); err != nil {
		return nil, err
	}
	m, v, err := s.requireViewable(ctx, in.MediaID)
	if err != nil {
		return nil, err
	}
	rows, err := s.gridRows(ctx, [][]byte{m.ID}, v)
	if err != nil || len(rows) == 0 {
		return nil, errors.New("media not found")
	}
	r := rows[0]
	persons := []personSummary{}
	if len(r.PersonIds) > 0 {
		prs, err := s.Q.ListPersonsByIDs(ctx, db.ListPersonsByIDsParams{Ids: r.PersonIds, IdentityID: sc.v.identityID()})
		if err == nil {
			for _, p := range prs {
				name := ""
				if p.DisplayName != nil {
					name = *p.DisplayName
				}
				persons = append(persons, personSummary{PersonID: ids.Encode(p.ID), DisplayName: name, EventSlug: p.EventSlug, FaceCount: int(p.FaceCount), IsMe: p.IsMe})
			}
		}
	}
	tags := []string{}
	if trs, err := s.Q.ListMediaTags(ctx, m.ID); err == nil {
		for _, t := range trs {
			tags = append(tags, t.Tag)
		}
	}
	out := map[string]any{
		"id": ids.Encode(m.ID), "kind": m.Kind, "state": string(m.State), "captured_at": m.CapturedAt, "captured_src": m.CapturedSrc,
		"width": r.Width, "height": r.Height, "duration_ms": m.DurationMs, "uploader_name": r.UploaderName, "uploaded_by_me": r.Mine,
		"like_count": r.LikeCount, "liked_by_me": r.Liked, "score": r.Score, "me": r.Me, "persons": persons, "face_count": len(r.PersonIds),
		"tags": tags, "caption": m.Caption, "place_name": m.PlaceName, "analyzed": m.AnalyzedAt != nil,
	}
	if m.EventID != nil {
		if ev, err := s.Q.GetEventByID(ctx, m.EventID); err == nil {
			out["event_slug"], out["event_title"] = ev.Event.Slug, ev.Event.Title
		}
	}
	return out, nil
}

func (s *Server) toolCreateAlbum(ctx context.Context, sc toolScope, args json.RawMessage) (any, error) {
	var in struct {
		Title     string   `json:"title"`
		MediaIDs  []string `json:"media_ids"`
		EventSlug string   `json:"event_slug"`
	}
	if err := decodeArgs(args, &in); err != nil {
		return nil, err
	}
	slug := in.EventSlug
	if slug == "" && sc.ev != nil {
		slug = sc.ev.Event.Slug
	}
	var slugPtr *string
	if slug != "" {
		slugPtr = &slug
	}
	a, err := s.createAlbum(ctx, slugPtr, in.Title, in.MediaIDs, "agent")
	if err != nil {
		return nil, err
	}
	return map[string]any{"album_id": a.Id, "title": a.Title, "count": a.Count, "event_slug": a.EventSlug}, nil
}

func (s *Server) toolLikeMedia(ctx context.Context, sc toolScope, args json.RawMessage) (any, error) {
	var in struct {
		MediaIDs []string `json:"media_ids"`
	}
	if err := decodeArgs(args, &in); err != nil {
		return nil, err
	}
	if len(in.MediaIDs) == 0 || len(in.MediaIDs) > 50 {
		return nil, errors.New("media_ids must hold 1 to 50 ids")
	}
	liked := 0
	for _, id := range in.MediaIDs {
		if _, err := s.setLike(ctx, id, true); err == nil {
			liked++
		}
	}
	return map[string]any{"liked": liked}, nil
}

func (s *Server) toolShareAlbum(ctx context.Context, sc toolScope, args json.RawMessage) (any, error) {
	var in struct {
		AlbumID       string `json:"album_id"`
		ExpiresDays   *int   `json:"expires_days"`
		AllowDownload *bool  `json:"allow_download"`
	}
	if err := decodeArgs(args, &in); err != nil {
		return nil, err
	}
	ac, err := s.albumByID(ctx, in.AlbumID)
	if err != nil {
		return nil, err
	}
	if !ac.canEdit() {
		return nil, errors.New("only the album's owner or a host can share it")
	}
	var expires *time.Time
	if in.ExpiresDays != nil {
		t := time.Now().UTC().Add(time.Duration(min(max(*in.ExpiresDays, 1), 365)) * 24 * time.Hour)
		expires = &t
	}
	allow := in.AllowDownload == nil || *in.AllowDownload
	sh, err := s.shareAlbum(ctx, ac.album.ID, sc.p.Actor(), expires, allow)
	if err != nil {
		return nil, err
	}
	return map[string]any{"share_id": sh.ShareId, "url": sh.Url, "expires_at": sh.ExpiresAt, "allow_download": sh.AllowDownload}, nil
}

func (s *Server) toolExportZip(ctx context.Context, sc toolScope, args json.RawMessage) (any, error) {
	var in struct {
		MediaIDs  []string `json:"media_ids"`
		Originals *bool    `json:"originals"`
	}
	if err := decodeArgs(args, &in); err != nil {
		return nil, err
	}
	if len(in.MediaIDs) == 0 {
		return nil, errors.New("media_ids is required")
	}
	t, err := s.zipTicket(ctx, in.MediaIDs, in.Originals == nil || *in.Originals)
	if err != nil {
		return nil, err
	}
	return map[string]any{"url": t.Url, "count": t.Count, "expires_at": t.ExpiresAt}, nil
}

func (s *Server) toolEventStats(ctx context.Context, sc toolScope, args json.RawMessage) (any, error) {
	var in struct {
		EventSlug string `json:"event_slug"`
	}
	if err := decodeArgs(args, &in); err != nil {
		return nil, err
	}
	sc, err := s.scopeForSlug(ctx, sc, in.EventSlug)
	if err != nil {
		return nil, err
	}
	type stats struct {
		EventSlug  string     `json:"event_slug"`
		Title      string     `json:"title"`
		StartsAt   time.Time  `json:"starts_at"`
		Photos     int        `json:"photos"`
		Videos     int        `json:"videos"`
		Ready      int        `json:"ready"`
		Processing int        `json:"processing"`
		Failed     int        `json:"failed"`
		People     int        `json:"people"`
		FacesDone  int        `json:"faces_done"`
		OfYou      int        `json:"of_you"`
		Likes      int        `json:"likes"`
		Clustered  *time.Time `json:"clustered_at"`
	}
	out := []stats{}
	events := sc.eventIDs
	if len(events) > 50 {
		events = events[:50]
	}
	for _, eid := range events {
		ev, err := s.Q.GetEventByID(ctx, eid)
		if err != nil {
			continue
		}
		c, err := s.Q.GetEventCounts(ctx, eid)
		if err != nil {
			return nil, err
		}
		pc, err := s.Q.EventPeopleCounts(ctx, db.EventPeopleCountsParams{EventID: eid, IdentityID: sc.v.identityID()})
		if err != nil {
			return nil, err
		}
		likes, _ := s.Q.CountEventLikes(ctx, eid)
		out = append(out, stats{
			EventSlug: ev.Event.Slug, Title: ev.Event.Title, StartsAt: ev.Event.StartsAt, Photos: int(c.Photos), Videos: int(c.Videos),
			Ready: int(c.Ready), Processing: int(c.Processing), Failed: int(c.Failed), People: int(pc.People), FacesDone: int(pc.FacesDone),
			OfYou: int(pc.OfYou), Likes: int(likes), Clustered: ev.Event.ClusteredAt,
		})
	}
	return map[string]any{"events": out, "count": len(out)}, nil
}

func (s *Server) toolRunQuery(ctx context.Context, sc toolScope, args json.RawMessage) (any, error) {
	var in struct {
		SQL string `json:"sql"`
	}
	if err := decodeArgs(args, &in); err != nil {
		return nil, err
	}
	return s.Exec.Run(ctx, sc.p.Actor(), sc.eventID(), in.SQL)
}

func (s *Server) toolRunSavedCommand(ctx context.Context, sc toolScope, args json.RawMessage) (any, error) {
	var in struct {
		CommandID string         `json:"command_id"`
		Params    map[string]any `json:"params"`
	}
	if err := decodeArgs(args, &in); err != nil {
		return nil, err
	}
	cmd, err := s.savedCommandFor(ctx, sc, in.CommandID)
	if err != nil {
		return nil, err
	}
	res, err := s.runSavedCommand(ctx, sc, cmd, in.Params)
	if err != nil {
		return nil, err
	}
	return res, nil
}

// agentResult shapes a command result for the UI: media when ids came back, else a stat.
func (s *Server) presentQuery(ctx context.Context, sc toolScope, title string, qr *agent.QueryResult) (api.AgentResult, error) {
	for _, col := range []string{"media_id", "id"} {
		vals := qr.Column(col)
		if len(vals) == 0 {
			continue
		}
		var list []string
		for _, v := range vals {
			if str, ok := v.(string); ok && len(str) == 22 {
				list = append(list, str)
			}
		}
		if len(list) == len(vals) {
			return s.mediaResult(ctx, sc, title, list)
		}
	}
	res := api.AgentResult{Kind: "stat", Title: &title}
	value := fmt.Sprintf("%d rows", qr.RowCount)
	if qr.RowCount == 1 && len(qr.Columns) == 1 {
		value = fmt.Sprint(qr.Rows[0][0])
	}
	res.Value = &value
	var b strings.Builder
	b.WriteString(strings.Join(qr.Columns, " | "))
	for i, row := range qr.Rows {
		if i >= 20 {
			b.WriteString("\n…")
			break
		}
		cells := make([]string, len(row))
		for j, c := range row {
			cells[j] = fmt.Sprint(c)
		}
		b.WriteString("\n" + strings.Join(cells, " | "))
	}
	detail := b.String()
	res.Detail = &detail
	return res, nil
}

// mediaResult hydrates a media AgentResult with the items the scope may see.
func (s *Server) mediaResult(ctx context.Context, sc toolScope, title string, list []string) (api.AgentResult, error) {
	visible, err := s.visibleMedia(ctx, sc, decodeIDs(list))
	if err != nil {
		return api.AgentResult{}, err
	}
	rows, err := s.gridRows(ctx, visible, sc.v)
	if err != nil {
		return api.AgentResult{}, err
	}
	idsOut := make([]api.Id, 0, len(rows))
	items := make([]api.GridItem, 0, len(rows))
	for _, r := range rows {
		idsOut = append(idsOut, ids.Encode(r.ID))
		items = append(items, gridItemOf(s, r))
	}
	if len(items) == 0 {
		return api.AgentResult{Kind: "empty", Title: &title}, nil
	}
	return api.AgentResult{Kind: "media", Title: &title, MediaIds: &idsOut, Items: &items}, nil
}
