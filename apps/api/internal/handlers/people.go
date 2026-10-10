package handlers

import (
	"context"
	"errors"
	"io"
	"math"
	"net/http"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"

	"yearbook/api/internal/apperr"
	"yearbook/api/internal/auth"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/jobs"
)

// Suggestion thresholds from docs/CONVENTIONS.md ("Person suggestions").
const (
	suggestMinFaces   = 3
	suggestRatio      = 2
	suggestYearGap    = 8
	suggestAgeSlack   = 6
	suggestMinCosine  = 0.45
	crossEventMaxList = 50
)

// personFields is the common subset of the person row types (list, get, mine).
type personFields struct {
	ID          []byte
	EventID     []byte
	DisplayName *string
	CoverFace   []byte
	FaceCount   int32
	Hidden      bool
	IdentityID  []byte
	IsMe        bool
	MediaCount  int32
}

// CropURL is the API path that serves a face crop (relative, like zip tickets).
func CropURL(faceID []byte) string { return "/api/v1/faces/" + ids.Encode(faceID) + "/crop.jpg" }

// personJSON shapes a person for the wire. canEdit = host or claimant.
func personJSON(p personFields, slug string, v viewer, suggested bool) api.Person {
	out := api.Person{
		Id:          ids.Encode(p.ID),
		EventSlug:   slug,
		DisplayName: p.DisplayName,
		Named:       p.DisplayName != nil && *p.DisplayName != "",
		FaceCount:   int(p.FaceCount),
		IsMe:        p.IsMe,
		Hidden:      p.Hidden,
	}
	mc := int(p.MediaCount)
	out.MediaCount = &mc
	linked := p.IdentityID != nil
	out.Linked = &linked
	canEdit := v.isHost() || p.IsMe
	out.CanEdit = &canEdit
	if suggested {
		out.SuggestedMe = &suggested
	}
	if p.CoverFace != nil {
		u := CropURL(p.CoverFace)
		out.CropUrl = &u
	}
	return out
}

func fieldsOfList(r db.ListPersonsRow) personFields {
	return personFields{r.ID, r.EventID, r.DisplayName, r.CoverFace, r.FaceCount, r.Hidden, r.IdentityID, r.IsMe, r.MediaCount}
}

func fieldsOfGet(r db.GetPersonRowRow) personFields {
	return personFields{r.ID, r.EventID, r.DisplayName, r.CoverFace, r.FaceCount, r.Hidden, r.IdentityID, r.IsMe, r.MediaCount}
}

// ListPeople returns the face clusters of an event, biggest first.
func (s *Server) ListPeople(ctx context.Context, req api.ListPeopleRequestObject) (api.ListPeopleResponseObject, error) {
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
	persons, err := s.Q.ListPersons(ctx, db.ListPersonsParams{EventID: row.Event.ID, IdentityID: v.identityID()})
	if err != nil {
		return nil, err
	}
	suggested, err := s.suggestedMe(ctx, row.Event.ID, v, persons)
	if err != nil {
		return nil, err
	}
	out := api.PeopleList{Persons: make([]api.Person, 0, len(persons))}
	unnamed := 0
	for _, p := range persons {
		if p.DisplayName == nil || *p.DisplayName == "" {
			unnamed++
		}
		out.Persons = append(out.Persons, personJSON(fieldsOfList(p), row.Event.Slug, v, string(p.ID) == string(suggested)))
	}
	out.UnnamedCount = &unnamed
	analyzing := false
	if row.Event.FacesEnabled {
		analyzing, err = s.Q.EventAnalyzing(ctx, row.Event.ID)
		if err != nil {
			return nil, err
		}
	}
	out.Analyzing = &analyzing
	return api.ListPeople200JSONResponse(out), nil
}

// suggestedMe applies the "Is this you?" heuristic: the person with the most faces among photos
// the viewer uploaded, if it has >= 3 faces and >= 2x the runner-up, and the viewer has not
// claimed anyone in this event yet.
func (s *Server) suggestedMe(ctx context.Context, eventID []byte, v viewer, persons []db.ListPersonsRow) ([]byte, error) {
	if v.p.Anonymous() {
		return nil, nil
	}
	for _, p := range persons {
		if p.IsMe {
			return nil, nil
		}
	}
	rows, err := s.Q.SuggestedMeCandidates(ctx, db.SuggestedMeCandidatesParams{EventID: eventID, UserID: v.p.UserID(), GuestID: v.guestID()})
	if err != nil || len(rows) == 0 {
		return nil, err
	}
	top := rows[0]
	if top.N < suggestMinFaces {
		return nil, nil
	}
	if len(rows) > 1 && top.N < suggestRatio*rows[1].N {
		return nil, nil
	}
	return top.PersonID, nil
}

// personCtx loads a person, its event and the viewer; 404 when the viewer may not see the event.
type personCtx struct {
	row  db.GetPersonRowRow
	ev   db.GetEventByIDRow
	v    viewer
	link *db.PersonLink
}

func (s *Server) personByID(ctx context.Context, id string) (personCtx, error) {
	raw, err := ids.Decode(id)
	if err != nil {
		return personCtx{}, apperr.NotFoundf("person not found")
	}
	ev, p, err := s.loadPerson(ctx, raw)
	if err != nil {
		return personCtx{}, err
	}
	v, err := s.viewerFor(ctx, ev.Event)
	if err != nil {
		return personCtx{}, err
	}
	if !v.canView() {
		return personCtx{}, apperr.Forbiddenf("the host has closed this album")
	}
	row, err := s.Q.GetPersonRow(ctx, db.GetPersonRowParams{PersonID: p.ID, IdentityID: v.identityID()})
	if err != nil {
		return personCtx{}, err
	}
	pc := personCtx{row: row, ev: ev, v: v}
	if row.IdentityID != nil {
		l, err := s.Q.GetPersonLink(ctx, p.ID)
		if err == nil {
			pc.link = &l
		}
	}
	return pc, nil
}

func (s *Server) loadPerson(ctx context.Context, raw []byte) (db.GetEventByIDRow, db.Person, error) {
	p, err := s.Q.GetPerson(ctx, raw)
	if errors.Is(err, pgx.ErrNoRows) {
		return db.GetEventByIDRow{}, p, apperr.NotFoundf("person not found")
	}
	if err != nil {
		return db.GetEventByIDRow{}, p, err
	}
	ev, err := s.Q.GetEventByID(ctx, p.EventID)
	return ev, p, err
}

func (pc personCtx) json() api.Person {
	return personJSON(fieldsOfGet(pc.row), pc.ev.Event.Slug, pc.v, false)
}

// canManage: host or the claimant may hide, split, merge or unclaim.
func (pc personCtx) canManage() bool { return pc.v.isHost() || pc.row.IsMe }

// requireIdentified rejects anonymous callers (no guest cookie and no session).
func requireIdentified(v viewer) error {
	if v.p.Anonymous() {
		return apperr.Unauthorizedf("no identity; call POST /events/{slug}/guests first")
	}
	return nil
}

// GetPerson returns one person.
func (s *Server) GetPerson(ctx context.Context, req api.GetPersonRequestObject) (api.GetPersonResponseObject, error) {
	pc, err := s.personByID(ctx, req.PersonId)
	if err != nil {
		return nil, err
	}
	return api.GetPerson200JSONResponse(pc.json()), nil
}

// UpdatePerson: anyone in the event may name a person; hosts and the claimant may hide it.
func (s *Server) UpdatePerson(ctx context.Context, req api.UpdatePersonRequestObject) (api.UpdatePersonResponseObject, error) {
	pc, err := s.personByID(ctx, req.PersonId)
	if err != nil {
		return nil, err
	}
	if err := requireIdentified(pc.v); err != nil {
		return nil, err
	}
	if req.Body == nil {
		return nil, apperr.BadRequestf("body required")
	}
	if req.Body.DisplayName != nil {
		name := strings.TrimSpace(*req.Body.DisplayName)
		if len(name) > 80 {
			return nil, apperr.BadRequestf("display_name may be at most 80 characters")
		}
		var namePtr *string
		if name != "" {
			namePtr = &name
		}
		if err := s.Q.UpdatePersonName(ctx, db.UpdatePersonNameParams{ID: pc.row.ID, DisplayName: namePtr}); err != nil {
			return nil, err
		}
	}
	if req.Body.Hidden != nil {
		if !pc.canManage() {
			return nil, apperr.Forbiddenf("only a host or the person themselves can hide a person")
		}
		if err := s.Q.UpdatePersonHidden(ctx, db.UpdatePersonHiddenParams{ID: pc.row.ID, Hidden: *req.Body.Hidden}); err != nil {
			return nil, err
		}
	}
	s.publishPeople(pc.ev.Event.ID, pc.ev.Event.Slug)
	pc, err = s.personByID(ctx, req.PersonId)
	if err != nil {
		return nil, err
	}
	return api.UpdatePerson200JSONResponse(pc.json()), nil
}

// ensureIdentity returns the caller's identity, creating one for a user (from the account) or a
// guest cookie (from the guest's name) when none exists yet.
func (s *Server) ensureIdentity(ctx context.Context, v viewer) (db.Identity, error) {
	if v.identity != nil {
		return *v.identity, nil
	}
	p := v.p
	params := db.CreateIdentityParams{ID: ids.New()}
	switch {
	case p.User != nil:
		params.UserID = p.User.ID
		params.DisplayName = p.User.DisplayName
		params.Birthdate = p.User.Birthdate
	case p.CookieID != nil:
		params.GuestCookieID = p.CookieID
		params.DisplayName = "Guest"
		if v.guest != nil && v.guest.DisplayName != nil && *v.guest.DisplayName != "" {
			params.DisplayName = *v.guest.DisplayName
		}
	default:
		return db.Identity{}, apperr.Unauthorizedf("")
	}
	id, err := s.Q.CreateIdentity(ctx, params)
	if err != nil {
		// A concurrent request may have created it; read it back.
		if existing, err2 := s.identityFor(ctx, p); err2 == nil && existing != nil {
			return *existing, nil
		}
		return db.Identity{}, err
	}
	return id, nil
}

// ClaimPerson links a person to the caller's identity ("This is me"). Idempotent for the same
// identity; a person already claimed by someone else is a conflict.
func (s *Server) ClaimPerson(ctx context.Context, req api.ClaimPersonRequestObject) (api.ClaimPersonResponseObject, error) {
	pc, err := s.personByID(ctx, req.PersonId)
	if err != nil {
		return nil, err
	}
	if err := requireIdentified(pc.v); err != nil {
		return nil, err
	}
	identity, err := s.ensureIdentity(ctx, pc.v)
	if err != nil {
		return nil, err
	}
	if pc.link != nil && string(pc.link.IdentityID) != string(identity.ID) && !pc.v.isHost() {
		return nil, apperr.Conflictf("this person is already claimed by someone else")
	}
	err = s.inTx(ctx, func(q *db.Queries) error {
		if err := q.UpsertPersonLink(ctx, db.UpsertPersonLinkParams{PersonID: pc.row.ID, IdentityID: identity.ID, ConfirmedBy: pc.v.p.Actor()}); err != nil {
			return err
		}
		if pc.row.DisplayName == nil || *pc.row.DisplayName == "" {
			name := identity.DisplayName
			return q.UpdatePersonName(ctx, db.UpdatePersonNameParams{ID: pc.row.ID, DisplayName: &name})
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	s.publishPeople(pc.ev.Event.ID, pc.ev.Event.Slug)
	pc, err = s.personByID(ctx, req.PersonId)
	if err != nil {
		return nil, err
	}
	return api.ClaimPerson200JSONResponse(pc.json()), nil
}

// UnclaimPerson removes the link. The claimant or a host.
func (s *Server) UnclaimPerson(ctx context.Context, req api.UnclaimPersonRequestObject) (api.UnclaimPersonResponseObject, error) {
	pc, err := s.personByID(ctx, req.PersonId)
	if err != nil {
		return nil, err
	}
	if err := requireIdentified(pc.v); err != nil {
		return nil, err
	}
	if pc.link != nil && !pc.canManage() {
		return nil, apperr.Forbiddenf("only the person themselves or a host can unlink")
	}
	if err := s.Q.DeletePersonLink(ctx, pc.row.ID); err != nil {
		return nil, err
	}
	s.publishPeople(pc.ev.Event.ID, pc.ev.Event.Slug)
	pc, err = s.personByID(ctx, req.PersonId)
	if err != nil {
		return nil, err
	}
	return api.UnclaimPerson200JSONResponse(pc.json()), nil
}

// MergePeople folds persons into the first id: faces move, a must-link constraint between the
// cover faces records the decision for the clusterer, counts are recomputed and the event is
// reclustered. Host, or the claimant when every person is theirs or unclaimed.
func (s *Server) MergePeople(ctx context.Context, req api.MergePeopleRequestObject) (api.MergePeopleResponseObject, error) {
	if req.Body == nil || len(req.Body.PersonIds) < 2 {
		return nil, apperr.BadRequestf("at least two person_ids required")
	}
	first, err := s.personByID(ctx, req.Body.PersonIds[0])
	if err != nil {
		return nil, err
	}
	if err := requireIdentified(first.v); err != nil {
		return nil, err
	}
	others := make([]personCtx, 0, len(req.Body.PersonIds)-1)
	seen := map[string]bool{string(first.row.ID): true}
	mineCount := 0
	if first.row.IsMe {
		mineCount++
	}
	for _, id := range req.Body.PersonIds[1:] {
		pc, err := s.personByID(ctx, id)
		if err != nil {
			return nil, err
		}
		if seen[string(pc.row.ID)] {
			continue
		}
		seen[string(pc.row.ID)] = true
		if string(pc.ev.Event.ID) != string(first.ev.Event.ID) {
			return nil, apperr.BadRequestf("persons must belong to the same event")
		}
		if pc.row.IsMe {
			mineCount++
		} else if pc.row.IdentityID != nil && !first.v.isHost() {
			return nil, apperr.Forbiddenf("one of the persons is claimed by someone else")
		}
		others = append(others, pc)
	}
	if !first.v.isHost() {
		if mineCount == 0 {
			return nil, apperr.Forbiddenf("only a host can merge persons that are not you")
		}
		if first.row.IdentityID != nil && !first.row.IsMe {
			return nil, apperr.Forbiddenf("the first person is claimed by someone else")
		}
	}
	if len(others) == 0 {
		return api.MergePeople200JSONResponse(first.json()), nil
	}
	actor := first.v.p.Actor()
	err = s.inTx(ctx, func(q *db.Queries) error {
		var link *db.PersonLink = first.link
		fromIDs := make([][]byte, 0, len(others))
		for _, o := range others {
			fromIDs = append(fromIDs, o.row.ID)
			if link == nil && o.link != nil {
				link = o.link
			}
			if first.row.CoverFace != nil && o.row.CoverFace != nil {
				if err := q.AddPersonConstraint(ctx, db.AddPersonConstraintParams{
					EventID: first.ev.Event.ID, FaceA: first.row.CoverFace, FaceB: o.row.CoverFace, Kind: "must_link", CreatedBy: actor,
				}); err != nil {
					return err
				}
			}
		}
		if err := q.MoveFacesToPerson(ctx, db.MoveFacesToPersonParams{ToPerson: first.row.ID, FromPersons: fromIDs}); err != nil {
			return err
		}
		if (first.row.DisplayName == nil || *first.row.DisplayName == "") && len(others) > 0 {
			for _, o := range others {
				if o.row.DisplayName != nil && *o.row.DisplayName != "" {
					if err := q.UpdatePersonName(ctx, db.UpdatePersonNameParams{ID: first.row.ID, DisplayName: o.row.DisplayName}); err != nil {
						return err
					}
					break
				}
			}
		}
		for _, id := range fromIDs {
			if err := q.DeletePerson(ctx, id); err != nil { // cascades person_links of the merged persons
				return err
			}
		}
		if link != nil && (first.link == nil) {
			if err := q.UpsertPersonLink(ctx, db.UpsertPersonLinkParams{PersonID: first.row.ID, IdentityID: link.IdentityID, ConfirmedBy: actor}); err != nil {
				return err
			}
		}
		if err := q.RecomputePerson(ctx, first.row.ID); err != nil {
			return err
		}
		return jobs.EnqueueClusterEvent(ctx, q, first.ev.Event.ID)
	})
	if err != nil {
		return nil, err
	}
	s.publishPeople(first.ev.Event.ID, first.ev.Event.Slug)
	first, err = s.personByID(ctx, req.Body.PersonIds[0])
	if err != nil {
		return nil, err
	}
	return api.MergePeople200JSONResponse(first.json()), nil
}

// SplitPerson moves the given faces into a new person and records a cannot-link constraint
// between the two cover faces. Host or claimant.
func (s *Server) SplitPerson(ctx context.Context, req api.SplitPersonRequestObject) (api.SplitPersonResponseObject, error) {
	pc, err := s.personByID(ctx, req.PersonId)
	if err != nil {
		return nil, err
	}
	if err := requireIdentified(pc.v); err != nil {
		return nil, err
	}
	if !pc.canManage() {
		return nil, apperr.Forbiddenf("only a host or the person themselves can split")
	}
	if req.Body == nil || len(req.Body.FaceIds) == 0 {
		return nil, apperr.BadRequestf("face_ids required")
	}
	faceIDs := make([][]byte, 0, len(req.Body.FaceIds))
	for _, f := range req.Body.FaceIds {
		raw, err := ids.Decode(f)
		if err != nil {
			return nil, apperr.BadRequestf("invalid face id " + f)
		}
		faceIDs = append(faceIDs, raw)
	}
	faces, err := s.Q.ListFacesOfPerson(ctx, pc.row.ID)
	if err != nil {
		return nil, err
	}
	if len(faceIDs) >= len(faces) {
		return nil, apperr.BadRequestf("a split must leave at least one face behind")
	}
	// The best of the moved faces becomes the new cover (faces come back best first).
	moving := map[string]bool{}
	for _, id := range faceIDs {
		moving[string(id)] = true
	}
	var newCover, oldCover []byte
	var newCoverQ *float32
	for _, f := range faces {
		if moving[string(f.ID)] {
			if newCover == nil {
				newCover, newCoverQ = f.ID, f.Quality
			}
		} else if oldCover == nil {
			oldCover = f.ID
		}
	}
	if newCover == nil {
		return nil, apperr.BadRequestf("none of the faces belong to this person")
	}
	newID := ids.New()
	actor := pc.v.p.Actor()
	err = s.inTx(ctx, func(q *db.Queries) error {
		if _, err := q.CreatePerson(ctx, db.CreatePersonParams{ID: newID, EventID: pc.ev.Event.ID, CoverFace: newCover, CoverFaceQuality: newCoverQ}); err != nil {
			return err
		}
		n, err := q.AssignFacesToPerson(ctx, db.AssignFacesToPersonParams{ToPerson: newID, FaceIds: faceIDs, FromPerson: pc.row.ID})
		if err != nil {
			return err
		}
		if n == 0 {
			return apperr.BadRequestf("none of the faces belong to this person")
		}
		if err := q.AddPersonConstraint(ctx, db.AddPersonConstraintParams{
			EventID: pc.ev.Event.ID, FaceA: newCover, FaceB: oldCover, Kind: "cannot_link", CreatedBy: actor,
		}); err != nil {
			return err
		}
		if err := q.RecomputePerson(ctx, pc.row.ID); err != nil {
			return err
		}
		if err := q.RecomputePerson(ctx, newID); err != nil {
			return err
		}
		return jobs.EnqueueClusterEvent(ctx, q, pc.ev.Event.ID)
	})
	if err != nil {
		return nil, err
	}
	s.publishPeople(pc.ev.Event.ID, pc.ev.Event.Slug)
	created, err := s.personByID(ctx, ids.Encode(newID))
	if err != nil {
		return nil, err
	}
	return api.SplitPerson200JSONResponse(created.json()), nil
}

// faceByID loads a face, its media and the viewer; the viewer must be able to see the media.
func (s *Server) faceByID(ctx context.Context, id string) (db.Face, db.Medium, viewer, error) {
	raw, err := ids.Decode(id)
	if err != nil {
		return db.Face{}, db.Medium{}, viewer{}, apperr.NotFoundf("face not found")
	}
	f, err := s.Q.GetFace(ctx, raw)
	if errors.Is(err, pgx.ErrNoRows) {
		return f, db.Medium{}, viewer{}, apperr.NotFoundf("face not found")
	}
	if err != nil {
		return f, db.Medium{}, viewer{}, err
	}
	m, err := s.mediaByID(ctx, ids.Encode(f.MediaID))
	if err != nil {
		return f, m, viewer{}, apperr.NotFoundf("face not found")
	}
	v, err := s.viewerForMedia(ctx, m)
	if err != nil {
		return f, m, v, err
	}
	if !v.canView() && !isUploader(m, v) {
		return f, m, v, apperr.Forbiddenf("the host has closed this album")
	}
	return f, m, v, nil
}

// FaceNotPerson flags a wrongly assigned face: cannot-link to the person's cover face, detach,
// recluster. Anyone in the event may flag.
func (s *Server) FaceNotPerson(ctx context.Context, req api.FaceNotPersonRequestObject) (api.FaceNotPersonResponseObject, error) {
	f, m, v, err := s.faceByID(ctx, req.FaceId)
	if err != nil {
		return nil, err
	}
	if err := requireIdentified(v); err != nil {
		return nil, err
	}
	if f.PersonID == nil {
		return api.FaceNotPerson204Response{}, nil
	}
	p, err := s.Q.GetPerson(ctx, f.PersonID)
	if err != nil {
		return nil, err
	}
	err = s.inTx(ctx, func(q *db.Queries) error {
		if err := q.DetachFace(ctx, f.ID); err != nil {
			return err
		}
		if err := q.RecomputePerson(ctx, p.ID); err != nil { // picks a new cover when this face was it
			return err
		}
		p2, err := q.GetPerson(ctx, p.ID)
		if err != nil {
			return err
		}
		if p2.CoverFace != nil {
			if err := q.AddPersonConstraint(ctx, db.AddPersonConstraintParams{
				EventID: m.EventID, FaceA: f.ID, FaceB: p2.CoverFace, Kind: "cannot_link", CreatedBy: v.p.Actor(),
			}); err != nil {
				return err
			}
		}
		return jobs.EnqueueClusterEvent(ctx, q, m.EventID)
	})
	if err != nil {
		return nil, err
	}
	s.publishPeople(m.EventID, v.event.Slug)
	return api.FaceNotPerson204Response{}, nil
}

// GetFaceCrop proxies the private crop with a private cache header. Authorisation is the
// media's event visibility.
func (s *Server) GetFaceCrop(ctx context.Context, req api.GetFaceCropRequestObject) (api.GetFaceCropResponseObject, error) {
	f, _, _, err := s.faceByID(ctx, req.FaceId)
	if err != nil {
		return nil, err
	}
	key := "f/" + ids.Encode(f.ID) + ".jpg"
	if f.CropKey != nil && *f.CropKey != "" {
		key = *f.CropKey
	}
	body, size, err := s.Store.Get(ctx, s.Store.Private, key)
	if err != nil {
		return nil, apperr.NotFoundf("crop not available yet")
	}
	return cropResponse{body: body, size: size}, nil
}

type cropResponse struct {
	body io.ReadCloser
	size int64
}

func (r cropResponse) VisitGetFaceCropResponse(w http.ResponseWriter) error {
	defer r.body.Close()
	w.Header().Set("Content-Type", "image/jpeg")
	w.Header().Set("Cache-Control", "private, max-age=86400")
	if r.size > 0 {
		w.Header().Set("Content-Length", strconv.FormatInt(r.size, 10))
	}
	w.WriteHeader(http.StatusOK)
	_, err := io.Copy(w, r.body)
	return err
}

// ListMediaFaces returns the faces of one item. Age estimates are shown to hosts only.
func (s *Server) ListMediaFaces(ctx context.Context, req api.ListMediaFacesRequestObject) (api.ListMediaFacesResponseObject, error) {
	m, v, err := s.requireViewable(ctx, req.MediaId)
	if err != nil {
		return nil, err
	}
	rows, err := s.Q.ListFacesForMedia(ctx, m.ID)
	if err != nil {
		return nil, err
	}
	out := api.ListMediaFaces200JSONResponse{Faces: make([]api.Face, 0, len(rows))}
	for _, r := range rows {
		face := api.Face{Id: ids.Encode(r.ID), MediaId: ids.Encode(r.MediaID), Bbox: make([]int, 0, 4), Quality: r.Quality}
		for _, b := range r.Bbox {
			face.Bbox = append(face.Bbox, int(b))
		}
		for len(face.Bbox) < 4 {
			face.Bbox = append(face.Bbox, 0)
		}
		if r.PersonID != nil {
			pid := ids.Encode(r.PersonID)
			face.PersonId = &pid
		}
		if v.isHost() {
			face.AgeEst = r.AgeEst
		}
		u := CropURL(r.ID)
		face.CropUrl = &u
		out.Faces = append(out.Faces, face)
	}
	return out, nil
}

// ListMyPeople lists the persons linked to my identity across events.
func (s *Server) ListMyPeople(ctx context.Context, _ api.ListMyPeopleRequestObject) (api.ListMyPeopleResponseObject, error) {
	user, err := requireUser(ctx)
	if err != nil {
		return nil, err
	}
	identity, err := s.identityFor(ctx, auth.FromContext(ctx))
	if err != nil {
		return nil, err
	}
	out := api.PeopleList{Persons: []api.Person{}}
	if identity == nil {
		return api.ListMyPeople200JSONResponse(out), nil
	}
	rows, err := s.Q.ListMyPersons(ctx, identity.ID)
	if err != nil {
		return nil, err
	}
	v := viewer{p: auth.FromContext(ctx), identity: identity}
	_ = user
	for _, r := range rows {
		pf := personFields{r.ID, r.EventID, r.DisplayName, r.CoverFace, r.FaceCount, r.Hidden, r.IdentityID, true, r.MediaCount}
		out.Persons = append(out.Persons, personJSON(pf, r.EventSlug, v, false))
	}
	return api.ListMyPeople200JSONResponse(out), nil
}

// ListMySuggestions finds unclaimed persons in my events that look like my claimed faces.
func (s *Server) ListMySuggestions(ctx context.Context, _ api.ListMySuggestionsRequestObject) (api.ListMySuggestionsResponseObject, error) {
	user, err := requireUser(ctx)
	if err != nil {
		return nil, err
	}
	identity, err := s.identityFor(ctx, auth.FromContext(ctx))
	if err != nil {
		return nil, err
	}
	out := api.ListMySuggestions200JSONResponse{Suggestions: []api.Suggestion{}}
	if identity == nil || !identity.LinkAcross {
		return out, nil
	}
	rows, err := s.Q.ListMySuggestions(ctx, db.ListMySuggestionsParams{IdentityID: identity.ID, UserID: user.ID, Birthdate: identity.Birthdate})
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		if r.Similarity < suggestMinCosine {
			continue
		}
		// Age consistency: when a birthdate is known and the capture years differ by more than
		// eight from the reference set, the estimated age must be within six years of the real one.
		if identity.Birthdate != nil && r.RefYear >= 0 && r.CandYear >= 0 && math.Abs(float64(r.CandYear-r.RefYear)) > suggestYearGap {
			if r.AgeEst < 0 || math.Abs(float64(r.AgeEst-r.ExactAge)) > suggestAgeSlack {
				continue
			}
		}
		row, err := s.Q.GetPersonRow(ctx, db.GetPersonRowParams{PersonID: r.PersonID, IdentityID: identity.ID})
		if err != nil {
			continue
		}
		v := viewer{p: auth.FromContext(ctx), identity: identity}
		startsAt := r.EventStartsAt
		out.Suggestions = append(out.Suggestions, api.Suggestion{
			Person: personJSON(fieldsOfGet(row), r.EventSlug, v, false), EventTitle: r.EventTitle, EventStartsAt: &startsAt, Confidence: r.Similarity,
		})
		if len(out.Suggestions) >= crossEventMaxList {
			break
		}
	}
	return out, nil
}

// DeleteMyFaceData removes identity links and the faces (and crops) of my linked persons.
func (s *Server) DeleteMyFaceData(ctx context.Context, _ api.DeleteMyFaceDataRequestObject) (api.DeleteMyFaceDataResponseObject, error) {
	if _, err := requireUser(ctx); err != nil {
		return nil, err
	}
	identity, err := s.identityFor(ctx, auth.FromContext(ctx))
	if err != nil {
		return nil, err
	}
	if identity == nil {
		return api.DeleteMyFaceData204Response{}, nil
	}
	faces, err := s.Q.ListFacesOfIdentity(ctx, identity.ID)
	if err != nil {
		return nil, err
	}
	events := map[string][]byte{}
	for _, f := range faces {
		if f.EventID != nil {
			events[string(f.EventID)] = f.EventID
		}
	}
	err = s.inTx(ctx, func(q *db.Queries) error {
		if err := q.DeleteFacesOfIdentity(ctx, identity.ID); err != nil {
			return err
		}
		return q.DeletePersonsOfIdentity(ctx, identity.ID) // cascades the links
	})
	if err != nil {
		return nil, err
	}
	for _, f := range faces {
		key := "f/" + ids.Encode(f.ID) + ".jpg"
		if f.CropKey != nil && *f.CropKey != "" {
			key = *f.CropKey
		}
		logErr(ctx, "delete crop", s.Store.Delete(ctx, s.Store.Private, key))
	}
	eventIDs := make([][]byte, 0, len(events))
	for _, id := range events {
		eventIDs = append(eventIDs, id)
	}
	if slugs, err := s.Q.ListEventSlugsForIDs(ctx, eventIDs); err == nil {
		for _, e := range slugs {
			s.publishPeople(e.ID, e.Slug)
		}
	}
	return api.DeleteMyFaceData204Response{}, nil
}
