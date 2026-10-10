package httpserver_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"math/rand"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"yearbook/api/internal/config"
	api "yearbook/api/internal/gen/api"
	"yearbook/api/internal/handlers"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/search"
	"yearbook/api/internal/testutil"
)

// Seeding helpers --------------------------------------------------------------------------------

func exec(t *testing.T, app *testutil.App, sql string, args ...any) {
	t.Helper()
	if _, err := app.Pool.Exec(context.Background(), sql, args...); err != nil {
		t.Fatalf("%s: %v", sql, err)
	}
}

func queryInt(t *testing.T, app *testutil.App, sql string, args ...any) int {
	t.Helper()
	var n int
	if err := app.Pool.QueryRow(context.Background(), sql, args...).Scan(&n); err != nil {
		t.Fatalf("%s: %v", sql, err)
	}
	return n
}

// unitVector is a deterministic pseudo-random unit vector; the same seed gives the same vector.
func unitVector(dim int, seed int64) []float32 {
	r := rand.New(rand.NewSource(seed))
	v := make([]float32, dim)
	var norm float64
	for i := range v {
		v[i] = float32(r.NormFloat64())
		norm += float64(v[i]) * float64(v[i])
	}
	norm = math.Sqrt(norm)
	for i := range v {
		v[i] = float32(float64(v[i]) / norm)
	}
	return v
}

// nearVector perturbs base a little (cosine stays well above 0.9).
func nearVector(base []float32, seed int64) []float32 {
	noise := unitVector(len(base), seed)
	out := make([]float32, len(base))
	var norm float64
	for i := range base {
		out[i] = base[i] + 0.2*noise[i]
		norm += float64(out[i]) * float64(out[i])
	}
	norm = math.Sqrt(norm)
	for i := range out {
		out[i] = float32(float64(out[i]) / norm)
	}
	return out
}

func vecLiteral(v []float32) string {
	parts := make([]string, len(v))
	for i, x := range v {
		parts[i] = fmt.Sprintf("%.6f", x)
	}
	return "[" + strings.Join(parts, ",") + "]"
}

type mediaOpts struct {
	owner, uploaderUser, uploaderGuest []byte
	score                              *float32
	caption                            string
	notBest                            bool
	noEvent                            bool
	kind                               string
}

// seedReady inserts one ready photo with a thumb and medium variant.
func seedReady(t *testing.T, app *testutil.App, eventID []byte, at time.Time, o mediaOpts) []byte {
	t.Helper()
	id := ids.New()
	var ev any = eventID
	if o.noEvent {
		ev = nil
	}
	kind := o.kind
	if kind == "" {
		kind = "photo"
	}
	var caption *string
	if o.caption != "" {
		caption = &o.caption
	}
	exec(t, app, `insert into media (id, event_id, owner_id, uploader_user, uploader_guest, kind, state, original_key, original_mime, variant_prefix,
		width, height, captured_at, captured_src, is_best_of_dup, caption, analyzed_at)
		values ($1, $2, $3, $4, $5, $6, 'ready', $7, 'image/jpeg', $8, 1200, 900, $9, 'exif', $10, $11, now())`,
		id, ev, o.owner, o.uploaderUser, o.uploaderGuest, kind, "o/x/"+ids.Encode(id)+".jpg", ids.NewString(), at, !o.notBest, caption)
	prefix := ids.NewString()
	exec(t, app, `insert into media_variants (media_id, name, key, width, height, bytes) values ($1,'thumb',$2,256,256,1000), ($1,'medium',$3,1200,900,50000)`,
		id, "v/"+prefix+"/thumb.webp", "v/"+prefix+"/medium.webp")
	if o.score != nil {
		exec(t, app, `insert into media_quality (media_id, score, aesthetic, sharpness) values ($1, $2, 5, 0.8)`, id, *o.score)
	}
	return id
}

func seedPerson(t *testing.T, app *testutil.App, eventID []byte, name string) []byte {
	t.Helper()
	id := ids.New()
	var n *string
	if name != "" {
		n = &name
	}
	exec(t, app, `insert into persons (id, event_id, display_name) values ($1, $2, $3)`, id, eventID, n)
	return id
}

// seedFace adds a face of personID on mediaID and refreshes the person's counters and cover.
func seedFace(t *testing.T, app *testutil.App, mediaID, eventID, personID []byte, emb []float32, quality float32, ageEst *float32) []byte {
	t.Helper()
	id := ids.New()
	exec(t, app, `insert into faces (id, media_id, event_id, person_id, bbox, det_score, quality, embedding, age_est, crop_key)
		values ($1, $2, $3, $4, '{10,10,100,100}', 0.99, $5, $6::vector, $7, $8)`,
		id, mediaID, eventID, personID, quality, vecLiteral(emb), ageEst, "f/"+ids.Encode(id)+".jpg")
	if personID != nil {
		exec(t, app, `update persons p set face_count = (select count(*) from faces where person_id = p.id),
			cover_face = (select id from faces where person_id = p.id order by quality desc nulls last limit 1) where p.id = $1`, personID)
	}
	return id
}

func f32(v float32) *float32 { return &v }

func (c *client) guest(slug string) api.Guest {
	c.t.Helper()
	var g api.Guest
	c.expect(c.do("POST", "/events/"+slug+"/guests", nil, &g), 200)
	return g
}

func (c *client) cookie(name string) string {
	u, _ := url.Parse(c.app.HTTP.URL)
	for _, ck := range c.http.Jar.Cookies(u) {
		if ck.Name == name {
			return ck.Value
		}
	}
	return ""
}

func decodeErr(t *testing.T, resp *http.Response) string {
	t.Helper()
	var e struct {
		Error struct{ Code, Message string }
	}
	_ = json.NewDecoder(resp.Body).Decode(&e)
	return e.Error.Message
}

// People -----------------------------------------------------------------------------------------

func TestPeopleListClaimAndMe(t *testing.T) {
	app := testutil.Start(t)
	host := newClient(t, app)
	host.signIn("host@example.org")
	ev := host.createEvent("Faces")
	eventID, _ := ids.Decode(ev.Id)

	guest := newClient(t, app)
	g := guest.guest(ev.Slug)
	guestRow, _ := ids.Decode(g.GuestId)
	base := time.Date(2026, 6, 6, 19, 0, 0, 0, time.UTC)
	m1 := seedReady(t, app, eventID, base, mediaOpts{uploaderGuest: guestRow})
	m2 := seedReady(t, app, eventID, base.Add(time.Minute), mediaOpts{uploaderGuest: guestRow})
	m3 := seedReady(t, app, eventID, base.Add(2*time.Minute), mediaOpts{uploaderGuest: guestRow})
	anna := seedPerson(t, app, eventID, "")
	bob := seedPerson(t, app, eventID, "Bob")
	hidden := seedPerson(t, app, eventID, "Shy")
	exec(t, app, "update persons set hidden = true where id = $1", hidden)
	e := unitVector(512, 1)
	for i, m := range [][]byte{m1, m2, m3} {
		seedFace(t, app, m, eventID, anna, nearVector(e, int64(10+i)), 0.9-float32(i)*0.1, nil)
	}
	seedFace(t, app, m1, eventID, bob, unitVector(512, 2), 0.5, nil)
	seedFace(t, app, m2, eventID, hidden, unitVector(512, 3), 0.5, nil)

	var list api.PeopleList
	guest.expect(guest.do("GET", "/events/"+ev.Slug+"/people", nil, &list), 200)
	if len(list.Persons) != 2 || list.Persons[0].FaceCount != 3 || list.Persons[1].Id != ids.Encode(bob) {
		t.Fatalf("people: %+v", list.Persons)
	}
	top := list.Persons[0]
	if top.SuggestedMe == nil || !*top.SuggestedMe || top.Named || top.CropUrl == nil || !strings.HasSuffix(*top.CropUrl, "/crop.jpg") {
		t.Fatalf("suggested_me/crop: %+v", top)
	}
	if list.UnnamedCount == nil || *list.UnnamedCount != 1 || list.Analyzing == nil || *list.Analyzing {
		t.Fatalf("counts: %+v", list)
	}

	// Anyone in the event may name; hiding needs host or claimant.
	var named api.Person
	guest.expect(guest.do("PATCH", "/people/"+top.Id, map[string]any{"display_name": "Anna"}, &named), 200)
	if !named.Named || *named.DisplayName != "Anna" {
		t.Fatalf("named: %+v", named)
	}
	guest.expect(guest.do("PATCH", "/people/"+ids.Encode(bob), map[string]any{"hidden": true}, nil), 403)

	// Claim: me flags on the grid, of_you counts, filter=me.
	var claimed api.Person
	guest.expect(guest.do("POST", "/people/"+top.Id+"/claim", nil, &claimed), 200)
	if !claimed.IsMe || claimed.Linked == nil || !*claimed.Linked || claimed.CanEdit == nil || !*claimed.CanEdit {
		t.Fatalf("claimed: %+v", claimed)
	}
	var evNow api.Event
	guest.expect(guest.do("GET", "/events/"+ev.Slug, nil, &evNow), 200)
	if evNow.Counts.OfYou == nil || *evNow.Counts.OfYou != 3 || evNow.Counts.People == nil || *evNow.Counts.People != 2 || evNow.Counts.FacesDone == nil || *evNow.Counts.FacesDone != 3 {
		t.Fatalf("counts: %+v", evNow.Counts)
	}
	var me api.MediaPage
	guest.expect(guest.do("GET", "/events/"+ev.Slug+"/media?filter=me", nil, &me), 200)
	if len(me.Items) != 3 || !me.Items[0].Me || len(me.Items[0].PersonIds) == 0 || me.Items[0].Analyzed == nil || !*me.Items[0].Analyzed {
		t.Fatalf("filter=me: %+v", me.Items)
	}
	var person api.MediaPage
	guest.expect(guest.do("GET", "/events/"+ev.Slug+"/media?filter=person:"+ids.Encode(bob), nil, &person), 200)
	if len(person.Items) != 1 || person.Items[0].Id != ids.Encode(m1) {
		t.Fatalf("filter=person: %+v", person.Items)
	}
	// The host sees no "me" and no suggestion, another guest is not offered Anna.
	var hostList api.PeopleList
	host.expect(host.do("GET", "/events/"+ev.Slug+"/people", nil, &hostList), 200)
	if hostList.Persons[0].IsMe || (hostList.Persons[0].SuggestedMe != nil && *hostList.Persons[0].SuggestedMe) {
		t.Fatalf("host view: %+v", hostList.Persons[0])
	}
	// A second guest cannot claim the same person.
	other := newClient(t, app)
	other.guest(ev.Slug)
	other.expect(other.do("POST", "/people/"+top.Id+"/claim", nil, nil), 409)
	// Claimant may hide themself; then the host still sees the row? No: hidden persons are omitted for others.
	guest.expect(guest.do("PATCH", "/people/"+top.Id, map[string]any{"hidden": true}, nil), 200)
	other.expect(other.do("GET", "/events/"+ev.Slug+"/people", nil, &list), 200)
	if len(list.Persons) != 1 {
		t.Fatalf("hidden person visible: %+v", list.Persons)
	}
	guest.expect(guest.do("GET", "/events/"+ev.Slug+"/people", nil, &list), 200)
	if len(list.Persons) != 2 || !list.Persons[0].IsMe {
		t.Fatalf("own hidden person missing: %+v", list.Persons)
	}
	var unclaimed api.Person
	guest.expect(guest.do("DELETE", "/people/"+top.Id+"/claim", nil, &unclaimed), 200)
	if unclaimed.IsMe {
		t.Fatal("still me after unclaim")
	}
	// Faces of one item, no age numbers for guests.
	var faces struct{ Faces []api.Face }
	guest.expect(guest.do("GET", "/media/"+ids.Encode(m1)+"/faces", nil, &faces), 200)
	if len(faces.Faces) != 2 || faces.Faces[0].PersonId == nil || faces.Faces[0].AgeEst != nil || len(faces.Faces[0].Bbox) != 4 {
		t.Fatalf("faces: %+v", faces.Faces)
	}
}

func TestMergeSplitNotPersonAndCrop(t *testing.T) {
	app := testutil.Start(t)
	host := newClient(t, app)
	host.signIn("host@example.org")
	ev := host.createEvent("Merge")
	eventID, _ := ids.Decode(ev.Id)
	base := time.Date(2026, 6, 6, 19, 0, 0, 0, time.UTC)
	var media [][]byte
	for i := range 4 {
		media = append(media, seedReady(t, app, eventID, base.Add(time.Duration(i)*time.Minute), mediaOpts{}))
	}
	a := seedPerson(t, app, eventID, "Anna")
	b := seedPerson(t, app, eventID, "")
	e := unitVector(512, 5)
	fa1 := seedFace(t, app, media[0], eventID, a, nearVector(e, 1), 0.9, nil)
	fa2 := seedFace(t, app, media[1], eventID, a, nearVector(e, 2), 0.8, nil)
	fb1 := seedFace(t, app, media[2], eventID, b, nearVector(e, 3), 0.7, nil)
	fb2 := seedFace(t, app, media[3], eventID, b, nearVector(e, 4), 0.6, nil)

	guest := newClient(t, app)
	guest.guest(ev.Slug)
	guest.expect(guest.do("POST", "/people/merge", map[string]any{"person_ids": []string{ids.Encode(a), ids.Encode(b)}}, nil), 403)

	var merged api.Person
	host.expect(host.do("POST", "/people/merge", map[string]any{"person_ids": []string{ids.Encode(a), ids.Encode(b)}}, &merged), 200)
	if merged.Id != ids.Encode(a) || merged.FaceCount != 4 {
		t.Fatalf("merged: %+v", merged)
	}
	host.expect(host.do("GET", "/people/"+ids.Encode(b), nil, nil), 404)
	if n := queryInt(t, app, "select count(*) from person_constraints where kind='must_link' and face_a=$1 and face_b=$2", fa1, fb1); n != 1 {
		t.Fatalf("must_link constraints: %d", n)
	}
	if n := queryInt(t, app, "select count(*) from jobs where kind='cluster_event' and payload->>'event_id'=$1 and done_at is null", ev.Id); n != 1 {
		t.Fatalf("cluster_event jobs: %d", n)
	}

	// Split two faces off into a new person.
	var split api.Person
	host.expect(host.do("POST", "/people/"+ids.Encode(a)+"/split", map[string]any{"face_ids": []string{ids.Encode(fb1), ids.Encode(fb2)}}, &split), 200)
	if split.Id == ids.Encode(a) || split.FaceCount != 2 {
		t.Fatalf("split: %+v", split)
	}
	var after api.Person
	host.expect(host.do("GET", "/people/"+ids.Encode(a), nil, &after), 200)
	if after.FaceCount != 2 {
		t.Fatalf("after split: %+v", after)
	}
	if n := queryInt(t, app, "select count(*) from person_constraints where kind='cannot_link'"); n != 1 {
		t.Fatalf("cannot_link constraints: %d", n)
	}
	host.expect(host.do("POST", "/people/"+ids.Encode(a)+"/split", map[string]any{"face_ids": []string{ids.Encode(fa1), ids.Encode(fa2)}}, nil), 400)

	// not-person detaches a face and records a cannot-link; the debounced job is still the same open one.
	guest.expect(guest.do("POST", "/faces/"+ids.Encode(fa2)+"/not-person", nil, nil), 204)
	if n := queryInt(t, app, "select count(*) from faces where id=$1 and person_id is null", fa2); n != 1 {
		t.Fatal("face still attached")
	}
	if n := queryInt(t, app, "select count(*) from jobs where kind='cluster_event' and done_at is null"); n != 1 {
		t.Fatalf("cluster_event jobs after not-person: %d", n)
	}

	// Crop proxy: the object lives in the private bucket; the API serves it with a private cache header.
	jpeg := append([]byte{0xFF, 0xD8, 0xFF, 0xE0}, randomBytes(64)...)
	if err := app.Server.Store.Put(context.Background(), app.Server.Store.Private, "f/"+ids.Encode(fa1)+".jpg", "image/jpeg", bytes.NewReader(jpeg), int64(len(jpeg))); err != nil {
		t.Fatal(err)
	}
	resp := guest.do("GET", "/faces/"+ids.Encode(fa1)+"/crop.jpg", nil, nil)
	guest.expect(resp, 200)
	body, _ := io.ReadAll(resp.Body)
	if resp.Header.Get("Content-Type") != "image/jpeg" || resp.Header.Get("Cache-Control") != "private, max-age=86400" || !bytes.Equal(body, jpeg) {
		t.Fatalf("crop: %v %d", resp.Header, len(body))
	}
	guest.expect(guest.do("GET", "/faces/"+ids.Encode(fb1)+"/crop.jpg", nil, nil), 404) // no object yet
	guest.expect(guest.do("GET", "/faces/"+ids.NewString()+"/crop.jpg", nil, nil), 404)
	host.expect(host.do("PATCH", "/events/"+ev.Slug, map[string]any{"guest_view": false}, nil), 200)
	anon := newClient(t, app)
	anon.expect(anon.do("GET", "/faces/"+ids.Encode(fa1)+"/crop.jpg", nil, nil), 403)
	host.expect(host.do("GET", "/faces/"+ids.Encode(fa1)+"/crop.jpg", nil, nil), 200)
}

func TestSuggestionsAndAgeRule(t *testing.T) {
	app := testutil.Start(t)
	c := newClient(t, app)
	c.signIn("mia@example.org")
	ev1 := c.createEvent("Then")
	ev2 := c.createEvent("Now")
	e1, _ := ids.Decode(ev1.Id)
	e2, _ := ids.Decode(ev2.Id)
	c.expect(c.do("PATCH", "/me", map[string]any{"birthdate": "1990-06-01"}, nil), 200)

	ref := unitVector(512, 42)
	then := time.Date(2016, 7, 1, 12, 0, 0, 0, time.UTC)
	now := time.Date(2026, 7, 1, 12, 0, 0, 0, time.UTC)
	m1 := seedReady(t, app, e1, then, mediaOpts{})
	mine := seedPerson(t, app, e1, "Mia")
	seedFace(t, app, m1, e1, mine, ref, 0.9, f32(26))
	c.expect(c.do("POST", "/people/"+ids.Encode(mine)+"/claim", nil, nil), 200)

	// Event 2, ten years later: a look-alike with a plausible age, one with an impossible age, a stranger.
	m2 := seedReady(t, app, e2, now, mediaOpts{})
	m3 := seedReady(t, app, e2, now.Add(time.Minute), mediaOpts{})
	m4 := seedReady(t, app, e2, now.Add(2*time.Minute), mediaOpts{})
	plausible := seedPerson(t, app, e2, "")
	tooYoung := seedPerson(t, app, e2, "")
	stranger := seedPerson(t, app, e2, "")
	seedFace(t, app, m2, e2, plausible, nearVector(ref, 7), 0.9, f32(35))
	seedFace(t, app, m3, e2, tooYoung, nearVector(ref, 8), 0.9, f32(19))
	seedFace(t, app, m4, e2, stranger, unitVector(512, 99), 0.9, f32(36))

	var out struct{ Suggestions []api.Suggestion }
	c.expect(c.do("GET", "/me/suggestions", nil, &out), 200)
	if len(out.Suggestions) != 1 || out.Suggestions[0].Person.Id != ids.Encode(plausible) || out.Suggestions[0].EventTitle != "Now" || out.Suggestions[0].Confidence < 0.45 {
		t.Fatalf("suggestions: %+v", out.Suggestions)
	}
	// Without a birthdate the age rule does not apply and the second look-alike appears too, ranked by similarity.
	c.expect(c.do("PATCH", "/me", map[string]any{"clear_birthdate": true}, nil), 200)
	c.expect(c.do("GET", "/me/suggestions", nil, &out), 200)
	if len(out.Suggestions) != 2 || out.Suggestions[0].Confidence < out.Suggestions[1].Confidence {
		t.Fatalf("suggestions without birthdate: %+v", out.Suggestions)
	}
	// Opting out of cross-event linking empties the list; /me/people lists the claimed person.
	c.expect(c.do("PATCH", "/me", map[string]any{"link_across": false}, nil), 200)
	c.expect(c.do("GET", "/me/suggestions", nil, &out), 200)
	if len(out.Suggestions) != 0 {
		t.Fatal("link_across=false must hide suggestions")
	}
	var mineList api.PeopleList
	c.expect(c.do("GET", "/me/people", nil, &mineList), 200)
	if len(mineList.Persons) != 1 || mineList.Persons[0].EventSlug != ev1.Slug {
		t.Fatalf("me/people: %+v", mineList.Persons)
	}
	// Deleting face data removes the linked person and its faces; photos stay.
	c.expect(c.do("DELETE", "/me/face-data", nil, nil), 204)
	if n := queryInt(t, app, "select count(*) from faces where media_id=$1", m1); n != 0 {
		t.Fatal("faces not deleted")
	}
	if n := queryInt(t, app, "select count(*) from media where id=$1 and state='ready'", m1); n != 1 {
		t.Fatal("photo must stay")
	}
}

// Search -----------------------------------------------------------------------------------------

type fakeEmbedder struct {
	vec []float32
	err error
}

func (f fakeEmbedder) Embed(context.Context, string) ([]float32, error) { return f.vec, f.err }

func withEmbedder(e search.Embedder) testutil.Option {
	return func(_ *config.Config, d *handlers.Deps) { d.Embedder = e }
}

func TestHybridSearch(t *testing.T) {
	ex := unitVector(1152, 100)
	app := testutil.Start(t, withEmbedder(fakeEmbedder{vec: ex}))
	host := newClient(t, app)
	host.signIn("host@example.org")
	ev := host.createEvent("Search")
	eventID, _ := ids.Decode(ev.Id)
	base := time.Date(2026, 6, 6, 19, 0, 0, 0, time.UTC)
	x := seedReady(t, app, eventID, base, mediaOpts{caption: "the cake table"})
	y := seedReady(t, app, eventID, base.Add(time.Minute), mediaOpts{caption: "Torte anschneiden"})
	z := seedReady(t, app, eventID, base.Add(2*time.Minute), mediaOpts{})
	for _, m := range []struct {
		id  []byte
		vec []float32
	}{{x, ex}, {y, nearVector(ex, 1)}, {z, unitVector(1152, 101)}} {
		exec(t, app, `insert into media_embeddings (media_id, model, embedding) values ($1, 'siglip2', $2::vector)`, m.id, vecLiteral(m.vec))
	}
	exec(t, app, `insert into media_tags (media_id, tag, source) values ($1, 'cake', 'tagger'), ($1, 'party', 'tagger')`, z)

	var page api.MediaPage
	host.expect(host.do("GET", "/events/"+ev.Slug+"/search?q=cake", nil, &page), 200)
	got := []string{}
	for _, it := range page.Items {
		got = append(got, it.Id)
	}
	if len(got) < 3 || got[0] != ids.Encode(x) || got[1] != ids.Encode(z) {
		t.Fatalf("cake ranking: %v (x=%s z=%s y=%s)", got, ids.Encode(x), ids.Encode(z), ids.Encode(y))
	}
	host.expect(host.do("GET", "/events/"+ev.Slug+"/search?q=Torte", nil, &page), 200)
	if len(page.Items) == 0 || page.Items[0].Id != ids.Encode(y) {
		t.Fatalf("Torte should rank the caption first: %+v", page.Items)
	}
	host.expect(host.do("GET", "/events/"+ev.Slug+"/search?q=", nil, nil), 400)

	// Cross-event search sees the same items; a stranger sees nothing.
	host.expect(host.do("GET", "/search?q=cake", nil, &page), 200)
	if len(page.Items) != 3 {
		t.Fatalf("/search: %d", len(page.Items))
	}
	other := newClient(t, app)
	other.signIn("other@example.org")
	other.expect(other.do("GET", "/search?q=cake", nil, &page), 200)
	if len(page.Items) != 0 {
		t.Fatalf("stranger sees %d", len(page.Items))
	}

	// Embedder down: text only (caption + tag), the vector-only item disappears.
	app2 := testutil.Start(t, withEmbedder(fakeEmbedder{err: errors.New("down")}))
	h2 := newClient(t, app2)
	h2.signIn("host@example.org")
	ev2 := h2.createEvent("Degraded")
	e2, _ := ids.Decode(ev2.Id)
	x2 := seedReady(t, app2, e2, base, mediaOpts{caption: "cake"})
	y2 := seedReady(t, app2, e2, base.Add(time.Minute), mediaOpts{})
	exec(t, app2, `insert into media_embeddings (media_id, model, embedding) values ($1, 'siglip2', $2::vector)`, y2, vecLiteral(ex))
	h2.expect(h2.do("GET", "/events/"+ev2.Slug+"/search?q=cake", nil, &page), 200)
	if len(page.Items) != 1 || page.Items[0].Id != ids.Encode(x2) {
		t.Fatalf("degraded search: %+v", page.Items)
	}
}

// Highlights and albums ----------------------------------------------------------------------------

func TestHighlightsDiversity(t *testing.T) {
	app := testutil.Start(t)
	host := newClient(t, app)
	host.signIn("host@example.org")
	ev := host.createEvent("Best")
	eventID, _ := ids.Decode(ev.Id)
	base := time.Date(2026, 6, 6, 20, 0, 0, 0, time.UTC)
	scores := []float32{0.9, 0.8, 0.7, 0.6, 0.5}
	want := map[string]bool{}
	for i, sc := range scores {
		id := seedReady(t, app, eventID, base.Add(time.Duration(i)*3*time.Minute), mediaOpts{score: f32(sc)})
		if i < 3 {
			want[ids.Encode(id)] = true
		}
	}
	seedReady(t, app, eventID, base.Add(5*time.Minute), mediaOpts{score: f32(0.95), notBest: true}) // duplicate, never shown
	late1 := seedReady(t, app, eventID, base.Add(60*time.Minute), mediaOpts{score: f32(0.4)})
	late2 := seedReady(t, app, eventID, base.Add(61*time.Minute), mediaOpts{score: f32(0.3)})
	want[ids.Encode(late1)], want[ids.Encode(late2)] = true, true

	var page api.MediaPage
	host.expect(host.do("GET", "/events/"+ev.Slug+"/best?limit=10", nil, &page), 200)
	if len(page.Items) != 5 {
		t.Fatalf("highlights: %d items", len(page.Items))
	}
	for i, it := range page.Items {
		if !want[it.Id] || it.Score == nil {
			t.Fatalf("unexpected item %s", it.Id)
		}
		if i > 0 && *it.Score > *page.Items[i-1].Score {
			t.Fatal("not in score order")
		}
	}
	var filtered api.MediaPage
	host.expect(host.do("GET", "/events/"+ev.Slug+"/media?filter=best&limit=2", nil, &filtered), 200)
	if len(filtered.Items) != 2 || filtered.NextCursor == nil {
		t.Fatalf("filter=best: %+v", filtered)
	}
	var next api.MediaPage
	host.expect(host.do("GET", "/events/"+ev.Slug+"/media?filter=best&limit=2&cursor="+url.QueryEscape(*filtered.NextCursor), nil, &next), 200)
	if len(next.Items) != 2 || next.Items[0].Id == filtered.Items[1].Id {
		t.Fatalf("best page 2: %+v", next.Items)
	}
}

func TestAlbumsShareAndDownloadGating(t *testing.T) {
	app := testutil.Start(t)
	host := newClient(t, app)
	host.signIn("host@example.org")
	ev := host.createEvent("Albums")
	eventID, _ := ids.Decode(ev.Id)
	base := time.Date(2026, 6, 6, 20, 0, 0, 0, time.UTC)
	a := host.uploadSingle(ev.Slug, "a.jpg", randomBytes(300))
	exec(t, app, "update media set state='ready', width=10, height=10 where id=$1", mustID(a.Id))
	b := seedReady(t, app, eventID, base, mediaOpts{})
	c := seedReady(t, app, eventID, base.Add(time.Minute), mediaOpts{})

	guest := newClient(t, app)
	guest.guest(ev.Slug)
	var album api.Album
	guest.expect(guest.do("POST", "/albums", map[string]any{"event_slug": ev.Slug, "title": "Meine Auswahl", "media_ids": []string{a.Id, ids.Encode(b)}}, &album), 201)
	if album.Count != 2 || album.Kind != api.AlbumKindManual || album.Cover == nil {
		t.Fatalf("album: %+v", album)
	}
	var detail api.AlbumDetail
	guest.expect(guest.do("GET", "/albums/"+album.Id, nil, &detail), 200)
	if len(detail.Items) != 2 || detail.Items[0].Id != a.Id || !detail.AllowDownload {
		t.Fatalf("detail: %+v", detail)
	}
	guest.expect(guest.do("PATCH", "/albums/"+album.Id, map[string]any{"add": []string{ids.Encode(c)}, "remove": []string{a.Id}, "title": "Auswahl"}, &detail), 200)
	if detail.Title != "Auswahl" || len(detail.Items) != 2 || detail.Items[1].Id != ids.Encode(c) {
		t.Fatalf("patched: %+v", detail)
	}
	other := newClient(t, app)
	other.guest(ev.Slug)
	other.expect(other.do("PATCH", "/albums/"+album.Id, map[string]any{"title": "nope"}, nil), 403)
	other.expect(other.do("DELETE", "/albums/"+album.Id, nil, nil), 403)
	var list struct{ Albums []api.Album }
	other.expect(other.do("GET", "/events/"+ev.Slug+"/albums", nil, &list), 200)
	if len(list.Albums) != 1 || list.Albums[0].CanEdit == nil || *list.Albums[0].CanEdit {
		t.Fatalf("event albums: %+v", list.Albums)
	}

	// Share without downloads; close the event to guests so only the share grants access.
	var share api.Share
	guest.expect(guest.do("POST", "/albums/"+album.Id+"/share", map[string]any{"allow_download": false, "expires_days": 7}, &share), 201)
	if share.AllowDownload || share.ExpiresAt == nil || !strings.Contains(share.Url, "/s/"+share.ShareId) {
		t.Fatalf("share: %+v", share)
	}
	host.expect(host.do("PATCH", "/events/"+ev.Slug, map[string]any{"guest_view": false}, nil), 200)
	anon := newClient(t, app)
	var shared api.AlbumDetail
	anon.expect(anon.do("GET", "/s/"+share.ShareId, nil, &shared), 200)
	if len(shared.Items) != 2 || shared.AllowDownload || shared.EventTitle == nil || *shared.EventTitle != "Albums" {
		t.Fatalf("shared: %+v", shared)
	}
	anon.expect(anon.do("GET", "/media/"+ids.Encode(b), nil, nil), 403)
	anon.expect(anon.do("GET", "/media/"+ids.Encode(b)+"?share="+share.ShareId, nil, nil), 200)
	anon.expect(anon.do("GET", "/media/"+ids.Encode(b)+"/original?share="+share.ShareId, nil, nil), 403)
	anon.expect(anon.do("POST", "/media/zip?share="+share.ShareId, map[string]any{"media_ids": []string{ids.Encode(b)}}, nil), 404)

	var open api.Share
	guest.expect(guest.do("POST", "/albums/"+album.Id+"/share", nil, &open), 201)
	anon.expect(anon.do("GET", "/media/"+ids.Encode(b)+"/original?share="+open.ShareId, nil, nil), 302)
	var ticket api.ZipTicket
	anon.expect(anon.do("POST", "/media/zip?share="+open.ShareId, map[string]any{"media_ids": []string{ids.Encode(b), a.Id}}, &ticket), 200)
	if ticket.Count != 1 { // a is no longer in the album
		t.Fatalf("zip via share: %+v", ticket)
	}
	anon.expect(anon.do("GET", "/s/"+ids.NewString(), nil, nil), 404)
	exec(t, app, "update shares set expires_at = now() - interval '1 minute' where id = $1", mustID(share.ShareId))
	anon.expect(anon.do("GET", "/s/"+share.ShareId, nil, nil), 404)

	// Likes schedule a debounced score refresh.
	host.expect(host.do("PUT", "/media/"+ids.Encode(b)+"/like", nil, nil), 200)
	host.expect(host.do("PUT", "/media/"+ids.Encode(c)+"/like", nil, nil), 200)
	if n := queryInt(t, app, "select count(*) from jobs where kind='recompute_scores' and payload->>'event_id'=$1 and done_at is null", ev.Id); n != 1 {
		t.Fatalf("recompute_scores jobs: %d", n)
	}
	guest.expect(guest.do("DELETE", "/albums/"+album.Id, nil, nil), 204)
	anon.expect(anon.do("GET", "/s/"+open.ShareId, nil, nil), 404)
}

func mustID(s string) []byte {
	b, _ := ids.Decode(s)
	return b
}

// Agent proxy and MCP ----------------------------------------------------------------------------

type fakeAgent struct {
	mu   sync.Mutex
	srv  *httptest.Server
	path string
	hdr  http.Header
	body map[string]any
}

func newFakeAgent(t *testing.T) *fakeAgent {
	f := &fakeAgent{}
	f.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		defer f.mu.Unlock()
		f.path, f.hdr = r.URL.Path, r.Header.Clone()
		f.body = map[string]any{}
		_ = json.NewDecoder(r.Body).Decode(&f.body)
		w.Header().Set("Content-Type", "application/json")
		if strings.HasSuffix(r.URL.Path, "/commands") {
			w.WriteHeader(201)
		}
		_, _ = w.Write([]byte(`{"ok":true,"path":"` + r.URL.Path + `"}`))
	}))
	t.Cleanup(f.srv.Close)
	return f
}

func withAgentURL(u string) testutil.Option {
	return func(cfg *config.Config, _ *handlers.Deps) { cfg.AgentURL = u }
}

func TestAgentProxy(t *testing.T) {
	fake := newFakeAgent(t)
	app := testutil.Start(t, withAgentURL(fake.srv.URL))
	host := newClient(t, app)
	me := host.signIn("host@example.org")
	ev := host.createEvent("Agent")

	anon := newClient(t, app)
	anon.expect(anon.do("POST", "/agent/messages", map[string]any{"text": "hi"}, nil), 401)
	host.expect(host.do("POST", "/agent/messages", map[string]any{"text": "hi", "event_slug": "nope"}, nil), 404)

	var out map[string]any
	host.expect(host.do("POST", "/agent/messages", map[string]any{"text": "Fotos von mir", "event_slug": ev.Slug}, &out), 200)
	if out["ok"] != true || fake.path != "/agent/messages" || fake.body["text"] != "Fotos von mir" {
		t.Fatalf("proxy: %+v %s %+v", out, fake.path, fake.body)
	}
	if fake.hdr.Get("X-Actor") != *me.Id || fake.hdr.Get("X-Actor-Kind") != "user" || fake.hdr.Get("X-Event-Slug") != ev.Slug || fake.hdr.Get("X-Locale") != "de" {
		t.Fatalf("headers: %v", fake.hdr)
	}
	if tok := fake.hdr.Get("X-Session-Token"); tok == "" || tok != host.cookie("yb_session") {
		t.Fatalf("session token: %q", tok)
	}
	// Guests are forwarded with their cookie id.
	guest := newClient(t, app)
	guest.guest(ev.Slug)
	guest.expect(guest.do("POST", "/agent/messages", map[string]any{"text": "hi", "event_slug": ev.Slug}, nil), 200)
	if fake.hdr.Get("X-Actor-Kind") != "guest" || fake.hdr.Get("X-Session-Token") != guest.cookie("yb_guest") || fake.hdr.Get("X-Actor") != guest.cookie("yb_guest") {
		t.Fatalf("guest headers: %v", fake.hdr)
	}
	// Save as chip and describe go to the service too.
	resp := host.do("POST", "/agent/commands", map[string]any{"turn_id": ids.NewString(), "label": "Meine Fotos"}, nil)
	host.expect(resp, 201)
	if fake.path != "/agent/commands" {
		t.Fatalf("save path: %s", fake.path)
	}
	eventID, _ := ids.Decode(ev.Id)
	m := seedReady(t, app, eventID, time.Now(), mediaOpts{})
	host.expect(host.do("POST", "/media/"+ids.Encode(m)+"/describe", nil, &out), 200)
	if fake.path != "/describe" || !strings.Contains(fmt.Sprint(fake.body["url"]), "/medium.webp") || fake.body["media_id"] != ids.Encode(m) {
		t.Fatalf("describe: %s %+v", fake.path, fake.body)
	}

	// No service: 503 agent_not_configured.
	down := testutil.Start(t, withAgentURL("http://127.0.0.1:1"))
	h2 := newClient(t, down)
	h2.signIn("host@example.org")
	r := h2.do("POST", "/agent/messages", map[string]any{"text": "hi"}, nil)
	if r.StatusCode != 503 || decodeErr(t, r) != "agent_not_configured" {
		t.Fatalf("down: %d", r.StatusCode)
	}
}

// bearerClient adds the MCP auth headers to every request.
type bearerClient struct {
	token, slug string
}

func (b bearerClient) RoundTrip(r *http.Request) (*http.Response, error) {
	r = r.Clone(r.Context())
	r.Header.Set("Authorization", "Bearer "+b.token)
	if b.slug != "" {
		r.Header.Set("X-Event-Slug", b.slug)
	}
	return http.DefaultTransport.RoundTrip(r)
}

func mcpSession(t *testing.T, app *testutil.App, token, slug string) *mcp.ClientSession {
	t.Helper()
	cl := mcp.NewClient(&mcp.Implementation{Name: "test", Version: "0"}, nil)
	sess, err := cl.Connect(context.Background(), &mcp.StreamableClientTransport{
		Endpoint: app.HTTP.URL + "/mcp", HTTPClient: &http.Client{Transport: bearerClient{token: token, slug: slug}},
	}, nil)
	if err != nil {
		t.Fatalf("mcp connect: %v", err)
	}
	t.Cleanup(func() { _ = sess.Close() })
	return sess
}

func callTool(t *testing.T, sess *mcp.ClientSession, name string, args map[string]any) (map[string]any, string, bool) {
	t.Helper()
	res, err := sess.CallTool(context.Background(), &mcp.CallToolParams{Name: name, Arguments: args})
	if err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	text := ""
	if len(res.Content) > 0 {
		if tc, ok := res.Content[0].(*mcp.TextContent); ok {
			text = tc.Text
		}
	}
	out := map[string]any{}
	if !res.IsError {
		_ = json.Unmarshal([]byte(text), &out)
	}
	return out, text, res.IsError
}

func TestMCPToolsAndRunQueryGuardrails(t *testing.T) {
	ex := unitVector(1152, 7)
	app := testutil.Start(t, withEmbedder(fakeEmbedder{vec: ex}))
	host := newClient(t, app)
	host.signIn("host@example.org")
	ev := host.createEvent("MCP")
	eventID, _ := ids.Decode(ev.Id)
	base := time.Date(2026, 6, 6, 20, 0, 0, 0, time.UTC)
	m1 := seedReady(t, app, eventID, base, mediaOpts{caption: "cake", score: f32(0.9)})
	m2 := seedReady(t, app, eventID, base.Add(time.Minute), mediaOpts{score: f32(0.5)})
	anna := seedPerson(t, app, eventID, "Anna")
	seedFace(t, app, m1, eventID, anna, unitVector(512, 1), 0.9, nil)
	seedFace(t, app, m2, eventID, anna, unitVector(512, 2), 0.8, nil)
	host.expect(host.do("PUT", "/media/"+ids.Encode(m1)+"/like", nil, nil), 200)

	// No bearer: 401 before any JSON-RPC.
	req, _ := http.NewRequest("POST", app.HTTP.URL+"/mcp", strings.NewReader(`{}`))
	req.Header.Set("Content-Type", "application/json")
	if r, _ := http.DefaultClient.Do(req); r.StatusCode != 401 {
		t.Fatalf("no bearer: %d", r.StatusCode)
	}

	sess := mcpSession(t, app, host.cookie("yb_session"), ev.Slug)
	tools, err := sess.ListTools(context.Background(), nil)
	if err != nil {
		t.Fatal(err)
	}
	names := map[string]bool{}
	for _, tl := range tools.Tools {
		names[tl.Name] = true
	}
	for _, want := range []string{"resolve_people", "search_media", "rank_best", "list_people", "describe_media", "create_album", "like_media", "share_album", "export_zip", "event_stats", "run_query", "run_saved_command"} {
		if !names[want] {
			t.Fatalf("tool %s missing from %v", want, names)
		}
	}

	out, _, isErr := callTool(t, sess, "resolve_people", map[string]any{"name": "ann"})
	if isErr || out["count"] != float64(1) {
		t.Fatalf("resolve_people: %+v", out)
	}
	out, _, isErr = callTool(t, sess, "search_media", map[string]any{"people_all": []string{ids.Encode(anna)}, "order": "best", "limit": 10})
	if isErr || out["count"] != float64(2) {
		t.Fatalf("search_media: %+v", out)
	}
	if got := out["media_ids"].([]any); got[0] != ids.Encode(m1) {
		t.Fatalf("search order: %v", got)
	}
	out, _, isErr = callTool(t, sess, "search_media", map[string]any{"text": "cake", "people_all": []string{ids.Encode(anna)}})
	if isErr || out["count"] != float64(1) || out["media_ids"].([]any)[0] != ids.Encode(m1) {
		t.Fatalf("search_media text: %+v", out)
	}
	out, _, isErr = callTool(t, sess, "search_media", map[string]any{"liked_by_me": true})
	if isErr || out["count"] != float64(1) {
		t.Fatalf("liked filter: %+v", out)
	}
	out, _, isErr = callTool(t, sess, "rank_best", map[string]any{"limit": 1})
	if isErr || out["media_ids"].([]any)[0] != ids.Encode(m1) {
		t.Fatalf("rank_best: %+v", out)
	}
	out, _, isErr = callTool(t, sess, "describe_media", map[string]any{"media_id": ids.Encode(m1)})
	if isErr || out["caption"] != "cake" || out["like_count"] != float64(1) || out["event_slug"] != ev.Slug {
		t.Fatalf("describe_media: %+v", out)
	}
	for _, k := range []string{"embedding", "email", "gps", "birthdate"} {
		if _, ok := out[k]; ok {
			t.Fatalf("describe_media leaks %s", k)
		}
	}
	out, _, isErr = callTool(t, sess, "event_stats", nil)
	if isErr || out["count"] != float64(1) || out["events"].([]any)[0].(map[string]any)["photos"] != float64(2) {
		t.Fatalf("event_stats: %+v", out)
	}
	out, _, isErr = callTool(t, sess, "create_album", map[string]any{"title": "Von Anna", "media_ids": []string{ids.Encode(m1)}})
	if isErr || out["count"] != float64(1) {
		t.Fatalf("create_album: %+v", out)
	}
	out, _, isErr = callTool(t, sess, "share_album", map[string]any{"album_id": out["album_id"]})
	if isErr || out["url"] == nil {
		t.Fatalf("share_album: %+v", out)
	}
	out, _, isErr = callTool(t, sess, "export_zip", map[string]any{"media_ids": []string{ids.Encode(m1), ids.Encode(m2)}})
	if isErr || out["count"] != float64(2) {
		t.Fatalf("export_zip: %+v", out)
	}

	// run_query: the real agent_ro role plus the parser.
	out, _, isErr = callTool(t, sess, "run_query", map[string]any{"sql": "select count(*) as n from v_media"})
	if isErr || out["row_count"] != float64(1) || out["rows"].([]any)[0].([]any)[0] != float64(2) {
		t.Fatalf("run_query count: %+v", out)
	}
	out, _, isErr = callTool(t, sess, "run_query", map[string]any{"sql": "select p.display_name, count(*) as n from v_faces f join v_persons p on p.id = f.person_id group by 1"})
	if isErr || out["rows"].([]any)[0].([]any)[0] != "Anna" {
		t.Fatalf("run_query join: %+v", out)
	}
	for sql, want := range map[string]string{
		"drop table media":    "only SELECT",
		"select * from media": `relation "media"`,
		"select * from users": `relation "users"`,
		"select pg_sleep(3)":  `function "pg_sleep"`,
		"select count(*) from generate_series(1, 300000000)":    "statement timeout",
		"select count(*) from v_media where no_such_column = 1": "no_such_column",
	} {
		_, text, isErr := callTool(t, sess, "run_query", map[string]any{"sql": sql})
		if !isErr || !strings.Contains(text, want) {
			t.Fatalf("%s: want error %q, got %v %q", sql, want, isErr, text)
		}
	}
	out, _, isErr = callTool(t, sess, "run_query", map[string]any{"sql": "select g from generate_series(1, 1000) g"})
	if isErr || out["row_count"] != float64(500) || out["truncated"] != true {
		t.Fatalf("row cap: %+v", out)
	}
	// The role itself has no table privileges even if a statement slipped past the parser.
	var denied string
	if err := app.Pool.QueryRow(context.Background(), "select has_table_privilege('agent_ro_login', 'media', 'select')::text").Scan(&denied); err != nil || denied != "false" {
		t.Fatalf("agent_ro_login must not read media: %q %v", denied, err)
	}

	// Guests connect with their cookie id and only see their event; outside the event scope the views are empty.
	guest := newClient(t, app)
	guest.guest(ev.Slug)
	gs := mcpSession(t, app, guest.cookie("yb_guest"), ev.Slug)
	out, _, isErr = callTool(t, gs, "run_query", map[string]any{"sql": "select count(*) from v_media where uploaded_by_me"})
	if isErr || out["rows"].([]any)[0].([]any)[0] != float64(0) {
		t.Fatalf("guest run_query: %+v", out)
	}
	other := host.createEvent("Other")
	stranger := newClient(t, app)
	stranger.guest(other.Slug)
	ss := mcpSession(t, app, stranger.cookie("yb_guest"), other.Slug)
	out, _, isErr = callTool(t, ss, "run_query", map[string]any{"sql": "select count(*) from v_media"})
	if isErr || out["rows"].([]any)[0].([]any)[0] != float64(0) {
		t.Fatalf("stranger sees media: %+v", out)
	}
	_, _, isErr = callTool(t, ss, "search_media", map[string]any{"event_slug": ev.Slug})
	if !isErr {
		t.Fatal("stranger must not search a foreign event")
	}
}

func TestSavedCommandRoundTrip(t *testing.T) {
	fake := newFakeAgent(t)
	app := testutil.Start(t, withAgentURL(fake.srv.URL))
	host := newClient(t, app)
	me := host.signIn("host@example.org")
	ev := host.createEvent("Chips")
	eventID, _ := ids.Decode(ev.Id)
	base := time.Date(2026, 6, 6, 20, 0, 0, 0, time.UTC)
	m1 := seedReady(t, app, eventID, base, mediaOpts{caption: "cake"})
	m2 := seedReady(t, app, eventID, base.Add(time.Minute), mediaOpts{})
	owner, _ := ids.Decode(*me.Id)

	// Rows as the agent service writes them.
	sqlCmd, searchCmd, pyCmd := ids.New(), ids.New(), ids.New()
	exec(t, app, `insert into saved_commands (id, owner, scope, name, label, description, params, sql_template, approved_at, event_id, shared, kind)
		values ($1, $2, 'event', 'newest_photos', 'Neueste', 'The newest n photos', '{"type":"object","properties":{"n":{"type":"integer"}}}', 'select id as media_id from v_media order by captured_at desc limit :n', now(), $3, true, 'sql')`, sqlCmd, owner, eventID)
	exec(t, app, `insert into saved_commands (id, owner, scope, name, label, description, params, sql_template, approved_at, event_id, kind, search_args)
		values ($1, $2, 'event', 'about', 'Thema', 'Photos about a topic', '{"type":"object","properties":{"topic":{"type":"string"}}}', '', now(), $3, 'search', '{"text": ":topic", "limit": 5}')`, searchCmd, owner, eventID)
	exec(t, app, `insert into saved_commands (id, owner, scope, name, label, description, params, sql_template, event_id, kind, code, created_by_agent)
		values ($1, $2, 'event', 'chart', 'Chart', 'Draws a chart', '{"type":"object"}', '', $3, 'python', 'print(1)', true)`, pyCmd, owner, eventID)

	var list struct{ Commands []api.SavedCommand }
	host.expect(host.do("GET", "/agent/commands?event_slug="+ev.Slug, nil, &list), 200)
	if len(list.Commands) != 3 {
		t.Fatalf("list: %+v", list.Commands)
	}
	kinds := map[string]api.SavedCommand{}
	for _, c := range list.Commands {
		kinds[string(*c.Kind)] = c
	}
	if kinds["python"].CreatedByAgent == nil || !*kinds["python"].CreatedByAgent || kinds["sql"].Shared == nil || !*kinds["sql"].Shared || *kinds["sql"].RunCount != 0 {
		t.Fatalf("fields: %+v", kinds)
	}

	var res api.AgentResponse
	host.expect(host.do("POST", "/agent/commands/"+ids.Encode(sqlCmd)+"/run", map[string]any{"params": map[string]any{"n": 1}}, &res), 200)
	if res.Result.Kind != "media" || res.Result.Items == nil || len(*res.Result.Items) != 1 || (*res.Result.Items)[0].Id != ids.Encode(m2) || res.Understood != "Neueste" || res.Saveable {
		t.Fatalf("sql run: %+v", res.Result)
	}
	if n := queryInt(t, app, "select run_count from saved_commands where id=$1", sqlCmd); n != 1 {
		t.Fatalf("run_count %d", n)
	}
	if n := queryInt(t, app, "select count(*) from agent_turns where final_call->>'name' = 'run_saved_command'"); n != 1 {
		t.Fatal("turn not logged")
	}
	host.expect(host.do("POST", "/agent/commands/"+ids.Encode(sqlCmd)+"/run", map[string]any{"params": map[string]any{}}, nil), 400) // missing n
	host.expect(host.do("POST", "/agent/commands/"+ids.Encode(searchCmd)+"/run", map[string]any{"params": map[string]any{"topic": "cake"}}, &res), 200)
	if res.Result.Kind != "media" || len(*res.Result.MediaIds) != 1 || (*res.Result.MediaIds)[0] != ids.Encode(m1) {
		t.Fatalf("search run: %+v", res.Result)
	}
	// python kind is proxied to the agent service.
	var raw map[string]any
	host.expect(host.do("POST", "/agent/commands/"+ids.Encode(pyCmd)+"/run", map[string]any{"params": map[string]any{"x": 1}}, &raw), 200)
	if fake.path != "/agent/commands/"+ids.Encode(pyCmd)+"/run" || fake.hdr.Get("X-Event-Slug") != ev.Slug {
		t.Fatalf("python proxy: %s %v", fake.path, fake.hdr)
	}

	// A guest of the event may run the shared one, not the private search command.
	guest := newClient(t, app)
	guest.guest(ev.Slug)
	guest.expect(guest.do("GET", "/agent/commands?event_slug="+ev.Slug, nil, &list), 200)
	if len(list.Commands) != 1 || list.Commands[0].Name != "newest_photos" {
		t.Fatalf("guest list: %+v", list.Commands)
	}
	guest.expect(guest.do("POST", "/agent/commands/"+ids.Encode(sqlCmd)+"/run", map[string]any{"params": map[string]any{"n": 2}}, &res), 200)
	guest.expect(guest.do("POST", "/agent/commands/"+ids.Encode(searchCmd)+"/run", map[string]any{"params": map[string]any{"topic": "cake"}}, nil), 404)
	guest.expect(guest.do("DELETE", "/agent/commands/"+ids.Encode(sqlCmd), nil, nil), 404)
	host.expect(host.do("DELETE", "/agent/commands/"+ids.Encode(sqlCmd), nil, nil), 204)
	host.expect(host.do("POST", "/agent/commands/"+ids.Encode(sqlCmd)+"/run", nil, nil), 404)

	// Through MCP as well.
	sess := mcpSession(t, app, host.cookie("yb_session"), ev.Slug)
	out, _, isErr := callTool(t, sess, "run_saved_command", map[string]any{"command_id": ids.Encode(searchCmd), "params": map[string]any{"topic": "cake"}})
	if isErr || out["kind"] != "media" {
		t.Fatalf("mcp run_saved_command: %+v", out)
	}
}

// Yearbook ----------------------------------------------------------------------------------------

func TestYearsAndRecap(t *testing.T) {
	app := testutil.Start(t)
	c := newClient(t, app)
	c.signIn("mia@example.org")
	var ev api.Event
	c.expect(c.do("POST", "/events", map[string]any{"title": "Sommer 2025", "starts_at": "2025-07-12T16:00:00Z"}, &ev), 201)
	eventID, _ := ids.Decode(ev.Id)
	var empty struct{ Years []api.YearSummary }
	c.expect(c.do("GET", "/me/years", nil, &empty), 200)
	if len(empty.Years) != 1 || empty.Years[0].Moments != 0 {
		t.Fatalf("years before claiming: %+v", empty.Years)
	}

	at := time.Date(2025, 7, 12, 18, 0, 0, 0, time.UTC)
	m1 := seedReady(t, app, eventID, at, mediaOpts{score: f32(0.9)})
	m2 := seedReady(t, app, eventID, at.Add(time.Minute), mediaOpts{score: f32(0.6)})
	seedReady(t, app, eventID, at.Add(2*time.Minute), mediaOpts{score: f32(0.95)})
	mia := seedPerson(t, app, eventID, "")
	tom := seedPerson(t, app, eventID, "Tom")
	seedFace(t, app, m1, eventID, mia, unitVector(512, 1), 0.95, nil)
	seedFace(t, app, m2, eventID, mia, unitVector(512, 2), 0.7, nil)
	seedFace(t, app, m1, eventID, tom, unitVector(512, 3), 0.8, nil)
	c.expect(c.do("POST", "/people/"+ids.Encode(mia)+"/claim", nil, nil), 200)

	var years struct{ Years []api.YearSummary }
	c.expect(c.do("GET", "/me/years", nil, &years), 200)
	if len(years.Years) != 1 || years.Years[0].Year != 2025 || years.Years[0].Moments != 2 {
		t.Fatalf("years: %+v", years.Years)
	}
	e := years.Years[0].Events[0]
	if e.Slug != ev.Slug || e.OfYou != 2 || e.Photos != 3 || e.OfYouItems == nil || len(*e.OfYouItems) != 2 || (*e.OfYouItems)[0].Id != ids.Encode(m1) || e.Cover == nil {
		t.Fatalf("event summary: %+v", e)
	}
	var recap api.YearRecap
	c.expect(c.do("GET", "/me/years/2025", nil, &recap), 200)
	if recap.Moments != 2 || len(recap.BestOfYou) != 2 || !recap.BestOfYou[0].Me || recap.Portrait == nil || recap.Portrait.Id != ids.Encode(m1) {
		t.Fatalf("recap: %+v", recap)
	}
	if len(recap.TopPeople) != 1 || recap.TopPeople[0].DisplayName != "Tom" || recap.TopPeople[0].Count != 1 || recap.TopPeople[0].CropUrl == nil {
		t.Fatalf("top people: %+v", recap.TopPeople)
	}
	var empty2024 api.YearRecap
	c.expect(c.do("GET", "/me/years/2024", nil, &empty2024), 200)
	if len(empty2024.Events) != 0 || empty2024.Portrait != nil {
		t.Fatalf("empty year: %+v", empty2024)
	}
	anon := newClient(t, app)
	anon.expect(anon.do("GET", "/me/years", nil, nil), 401)
}

// Import and library ---------------------------------------------------------------------------------

func withOperator(email string) testutil.Option {
	return func(cfg *config.Config, _ *handlers.Deps) { cfg.OperatorEmail = email }
}

func TestImportFlow(t *testing.T) {
	app := testutil.Start(t, withOperator("op@example.org"))
	c := newClient(t, app)
	c.signIn("mia@example.org")

	var init api.ImportInit
	c.expect(c.do("POST", "/imports", map[string]any{"kind": "zip", "filename": "photos.zip", "size": 2048}, &init), 201)
	if init.State != api.ImportInitStateUploading || init.Upload == nil || init.Upload.Mode != api.UploadInitModeSingle || init.Upload.Url == nil {
		t.Fatalf("init: %+v", init)
	}
	data := randomBytes(2048)
	putObject(t, *init.Upload.Url, *init.Upload.Headers, data)
	var imp api.Import
	c.expect(c.do("POST", "/imports/"+init.Id+"/complete", nil, &imp), 200)
	if imp.State != api.ImportStateQueued || imp.Stats.Found != 0 {
		t.Fatalf("complete: %+v", imp)
	}
	if n := queryInt(t, app, "select count(*) from jobs where kind='import' and payload->>'import_id'=$1 and done_at is null", init.Id); n != 1 {
		t.Fatalf("import jobs: %d", n)
	}
	var list struct{ Imports []api.Import }
	c.expect(c.do("GET", "/imports", nil, &list), 200)
	if len(list.Imports) != 1 || list.Imports[0].Id != init.Id {
		t.Fatalf("list: %+v", list.Imports)
	}
	c.expect(c.do("GET", "/imports/"+init.Id, nil, &imp), 200)
	// Cancel is allowed while queued and removes the job; running imports cannot be cancelled.
	c.expect(c.do("DELETE", "/imports/"+init.Id, nil, nil), 204)
	if n := queryInt(t, app, "select count(*) from jobs where kind='import' and done_at is null"); n != 0 {
		t.Fatalf("job not removed: %d", n)
	}
	exec(t, app, "update imports set state='running' where id=$1", mustID(init.Id))
	c.expect(c.do("DELETE", "/imports/"+init.Id, nil, nil), 409)
	// A size mismatch is refused.
	c.expect(c.do("POST", "/imports", map[string]any{"kind": "takeout", "filename": "takeout.zip", "size": 100}, &init), 201)
	putObject(t, *init.Upload.Url, *init.Upload.Headers, randomBytes(50))
	c.expect(c.do("POST", "/imports/"+init.Id+"/complete", nil, nil), 409)
	// Other users cannot see it; folder imports are for the operator only.
	other := newClient(t, app)
	other.signIn("other@example.org")
	other.expect(other.do("GET", "/imports/"+init.Id, nil, nil), 404)
	other.expect(other.do("POST", "/imports", map[string]any{"kind": "folder", "path": "/srv/photos"}, nil), 403)
	op := newClient(t, app)
	op.signIn("op@example.org")
	var folder api.ImportInit
	op.expect(op.do("POST", "/imports", map[string]any{"kind": "folder", "path": "/srv/photos"}, &folder), 201)
	if folder.State != api.ImportInitStateQueued || folder.Upload != nil {
		t.Fatalf("folder import: %+v", folder)
	}
	if n := queryInt(t, app, "select count(*) from jobs where kind='import' and payload->>'import_id'=$1", folder.Id); n != 1 {
		t.Fatal("folder job missing")
	}
	op.expect(op.do("POST", "/imports", map[string]any{"kind": "folder", "path": "relative"}, nil), 400)
}

func TestLibraryAndAssignment(t *testing.T) {
	app := testutil.Start(t)
	c := newClient(t, app)
	me := c.signIn("mia@example.org")
	owner, _ := ids.Decode(*me.Id)
	ev := c.createEvent("Lib")
	eventID, _ := ids.Decode(ev.Id)
	base := time.Date(2026, 6, 6, 20, 0, 0, 0, time.UTC)
	lib1 := seedReady(t, app, nil, base, mediaOpts{noEvent: true, owner: owner})
	lib2 := seedReady(t, app, nil, base.Add(time.Minute), mediaOpts{noEvent: true, owner: owner})
	inEvent := seedReady(t, app, eventID, base.Add(2*time.Minute), mediaOpts{owner: owner})
	seedFace(t, app, lib2, nil, nil, unitVector(512, 1), 0.9, nil)

	var page api.MediaPage
	c.expect(c.do("GET", "/me/library", nil, &page), 200)
	if len(page.Items) != 3 || page.Items[0].Id != ids.Encode(inEvent) {
		t.Fatalf("library: %+v", page.Items)
	}
	c.expect(c.do("GET", "/me/library?unassigned=true&limit=1", nil, &page), 200)
	if len(page.Items) != 1 || page.NextCursor == nil || page.Items[0].Id != ids.Encode(lib2) {
		t.Fatalf("unassigned: %+v", page)
	}
	// The event listing has a library filter for the owner too.
	c.expect(c.do("GET", "/events/"+ev.Slug+"/media?filter=library", nil, &page), 200)
	if len(page.Items) != 2 {
		t.Fatalf("filter=library: %d", len(page.Items))
	}
	// Move one into the event: faces follow, the event gets a recluster, the item appears in the grid.
	var item api.GridItem
	c.expect(c.do("PUT", "/media/"+ids.Encode(lib2)+"/event", map[string]any{"event_slug": ev.Slug}, &item), 200)
	if item.Id != ids.Encode(lib2) {
		t.Fatalf("assigned: %+v", item)
	}
	if n := queryInt(t, app, "select count(*) from faces where media_id=$1 and event_id=$2", lib2, eventID); n != 1 {
		t.Fatal("face did not follow")
	}
	if n := queryInt(t, app, "select count(*) from jobs where kind='cluster_event' and payload->>'event_id'=$1 and done_at is null", ev.Id); n != 1 {
		t.Fatal("no cluster_event job")
	}
	c.expect(c.do("GET", "/me/library?unassigned=true", nil, &page), 200)
	if len(page.Items) != 1 || page.Items[0].Id != ids.Encode(lib1) {
		t.Fatalf("unassigned after move: %+v", page.Items)
	}
	c.expect(c.do("GET", "/events/"+ev.Slug+"/media", nil, &page), 200)
	if len(page.Items) != 2 {
		t.Fatalf("event grid: %d", len(page.Items))
	}
	// Back to the library with null; strangers and their events are refused.
	c.expect(c.do("PUT", "/media/"+ids.Encode(lib2)+"/event", map[string]any{"event_slug": nil}, &item), 200)
	other := newClient(t, app)
	other.signIn("other@example.org")
	other.expect(other.do("PUT", "/media/"+ids.Encode(lib1)+"/event", map[string]any{"event_slug": ev.Slug}, nil), 404)
	theirs := other.createEvent("Theirs")
	c.expect(c.do("PUT", "/media/"+ids.Encode(lib1)+"/event", map[string]any{"event_slug": theirs.Slug}, nil), 403)
	other.expect(other.do("GET", "/me/library", nil, &page), 200)
	if len(page.Items) != 0 {
		t.Fatal("library leaks")
	}
}

// Mail, spec, docs ------------------------------------------------------------------------------------

func TestTurkishMagicLinkMail(t *testing.T) {
	app := testutil.Start(t)
	c := newClient(t, app)
	c.expect(c.do("POST", "/auth/magic", map[string]any{"email": "ayse@example.org", "locale": "tr"}, nil), 204)
	msg, _ := app.Mail.Last()
	if msg.Subject != "Yearbook giriş bağlantın" || !strings.Contains(msg.Text, "15 dakika") || !tokenRe.MatchString(msg.Text) {
		t.Fatalf("tr mail: %+v", msg)
	}
	c.expect(c.do("POST", "/auth/magic", map[string]any{"email": "ayse@example.org", "locale": "en"}, nil), 204)
	msg, _ = app.Mail.Last()
	if msg.Subject != "Your Yearbook sign-in link" {
		t.Fatalf("en mail: %+v", msg)
	}
	// The account locale is remembered and used when the request carries none.
	c.signIn("ayse@example.org")
	c.expect(c.do("PATCH", "/me", map[string]any{"locale": "tr"}, nil), 200)
	c.expect(c.do("POST", "/auth/magic", map[string]any{"email": "ayse@example.org"}, nil), 204)
	msg, _ = app.Mail.Last()
	if msg.Subject != "Yearbook giriş bağlantın" {
		t.Fatalf("account locale mail: %+v", msg)
	}
	c.expect(c.do("PATCH", "/me", map[string]any{"locale": "xx"}, nil), 400)
}

func TestOpenAPIAndDocs(t *testing.T) {
	app := testutil.Start(t)
	resp, err := http.Get(app.HTTP.URL + "/api/v1/openapi.json")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 || !strings.HasPrefix(resp.Header.Get("Content-Type"), "application/json") {
		t.Fatalf("openapi.json: %d %s", resp.StatusCode, resp.Header.Get("Content-Type"))
	}
	var spec struct {
		Openapi string
		Paths   map[string]any
		Info    struct{ Title string }
	}
	if err := json.NewDecoder(resp.Body).Decode(&spec); err != nil {
		t.Fatal(err)
	}
	if spec.Info.Title != "Yearbook API" || spec.Paths["/events/{slug}/people"] == nil || spec.Paths["/agent/messages"] == nil || len(spec.Paths) < 50 {
		t.Fatalf("spec: %s %d paths", spec.Info.Title, len(spec.Paths))
	}
	docs, err := http.Get(app.HTTP.URL + "/api/docs")
	if err != nil {
		t.Fatal(err)
	}
	defer docs.Body.Close()
	html, _ := io.ReadAll(docs.Body)
	if docs.StatusCode != 200 || !strings.HasPrefix(docs.Header.Get("Content-Type"), "text/html") ||
		!bytes.Contains(html, []byte("cdnjs.cloudflare.com/ajax/libs/swagger-ui/")) || !bytes.Contains(html, []byte(`url: "/api/v1/openapi.json"`)) {
		t.Fatalf("docs: %d %.200s", docs.StatusCode, html)
	}
}
