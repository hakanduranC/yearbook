package httpserver_test

import (
	"archive/zip"
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"regexp"
	"strings"
	"testing"
	"time"

	api "yearbook/api/internal/gen/api"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/testutil"
)

// client is an HTTP client with its own cookie jar, i.e. one browser.
type client struct {
	t    *testing.T
	app  *testutil.App
	http *http.Client
}

func newClient(t *testing.T, app *testutil.App) *client {
	jar, _ := cookiejar.New(nil)
	return &client{t: t, app: app, http: &http.Client{Jar: jar, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
}

// do sends a JSON request with the web origin set (so the CSRF check passes) and decodes into out.
func (c *client) do(method, path string, body any, out any) *http.Response {
	c.t.Helper()
	var rd io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		rd = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, c.app.HTTP.URL+"/api/v1"+path, rd)
	if err != nil {
		c.t.Fatal(err)
	}
	req.Header.Set("Origin", c.app.Cfg.WebOrigin)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.http.Do(req)
	if err != nil {
		c.t.Fatal(err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	resp.Body = io.NopCloser(bytes.NewReader(data))
	if out != nil && len(data) > 0 && resp.StatusCode < 300 {
		if err := json.Unmarshal(data, out); err != nil {
			c.t.Fatalf("%s %s: decode %q: %v", method, path, data, err)
		}
	}
	return resp
}

func (c *client) expect(resp *http.Response, status int) {
	c.t.Helper()
	if resp.StatusCode != status {
		body, _ := io.ReadAll(resp.Body)
		c.t.Fatalf("%s %s: want %d, got %d: %s", resp.Request.Method, resp.Request.URL.Path, status, resp.StatusCode, body)
	}
}

var tokenRe = regexp.MustCompile(`token=([A-Za-z0-9_-]+)`)

// signIn runs the magic link flow for email and leaves the session cookie in the jar.
func (c *client) signIn(email string) api.Me {
	c.t.Helper()
	c.expect(c.do("POST", "/auth/magic", map[string]any{"email": email, "next": "/new"}, nil), 204)
	msg, ok := c.app.Mail.Last()
	if !ok {
		c.t.Fatal("no mail sent")
	}
	m := tokenRe.FindStringSubmatch(msg.Text)
	if m == nil {
		c.t.Fatalf("no token in mail: %q", msg.Text)
	}
	var verified api.VerifyResponse
	c.expect(c.do("POST", "/auth/verify", map[string]any{"token": m[1]}, &verified), 200)
	if verified.Next != "/new" || !verified.Me.Authenticated {
		c.t.Fatalf("unexpected verify response: %+v", verified)
	}
	return verified.Me
}

func (c *client) createEvent(title string) api.Event {
	c.t.Helper()
	var ev api.Event
	c.expect(c.do("POST", "/events", map[string]any{"title": title, "starts_at": time.Now().Add(-2 * time.Hour).UTC()}, &ev), 201)
	return ev
}

// uploadSingle runs intent → PUT → complete for one in-memory file and returns the queued item.
func (c *client) uploadSingle(slug string, name string, data []byte) api.GridItem {
	c.t.Helper()
	var intents api.UploadIntentResponse
	c.expect(c.do("POST", "/events/"+slug+"/uploads", map[string]any{"files": []map[string]any{
		{"client_id": "c1", "name": name, "size": len(data), "type": "image/jpeg"},
	}}, &intents), 200)
	if len(intents.Uploads) != 1 || intents.Uploads[0].Mode != api.UploadInitModeSingle || intents.Uploads[0].Url == nil {
		c.t.Fatalf("unexpected intent: %+v", intents)
	}
	up := intents.Uploads[0]
	putObject(c.t, *up.Url, *up.Headers, data)
	var item api.GridItem
	c.expect(c.do("POST", "/uploads/"+up.MediaId+"/complete", nil, &item), 200)
	return item
}

// putObject PUTs bytes to a presigned URL with the headers the API asked for.
func putObject(t *testing.T, u string, headers map[string]string, data []byte) {
	t.Helper()
	req, _ := http.NewRequest(http.MethodPut, u, bytes.NewReader(data))
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	req.ContentLength = int64(len(data))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("presigned PUT: %d %s", resp.StatusCode, body)
	}
}

func randomBytes(n int) []byte {
	b := make([]byte, n)
	rand.Read(b)
	return b
}

func TestMagicLinkRoundTrip(t *testing.T) {
	app := testutil.Start(t)
	c := newClient(t, app)

	var anon api.Me
	c.expect(c.do("GET", "/me", nil, &anon), 200)
	if anon.Authenticated {
		t.Fatal("expected anonymous")
	}

	me := c.signIn("anna.schmidt@example.org")
	if me.DisplayName == nil || *me.DisplayName != "Anna Schmidt" {
		t.Fatalf("display name from local part: %+v", me.DisplayName)
	}
	var again api.Me
	c.expect(c.do("GET", "/me", nil, &again), 200)
	if !again.Authenticated || *again.Email != "anna.schmidt@example.org" {
		t.Fatalf("session not kept: %+v", again)
	}

	// A token can be used only once.
	msg, _ := app.Mail.Last()
	tok := tokenRe.FindStringSubmatch(msg.Text)[1]
	c.expect(c.do("POST", "/auth/verify", map[string]any{"token": tok}, nil), 400)

	c.expect(c.do("POST", "/auth/logout", nil, nil), 204)
	var out api.Me
	c.expect(c.do("GET", "/me", nil, &out), 200)
	if out.Authenticated {
		t.Fatal("expected logged out")
	}

	// Mutations without an allowed Origin are refused.
	req, _ := http.NewRequest("POST", app.HTTP.URL+"/api/v1/auth/magic", strings.NewReader(`{"email":"x@y.z"}`))
	req.Header.Set("Content-Type", "application/json")
	resp, _ := http.DefaultClient.Do(req)
	if resp.StatusCode != 403 {
		t.Fatalf("csrf: want 403, got %d", resp.StatusCode)
	}
}

func TestCreateEvent(t *testing.T) {
	app := testutil.Start(t)
	c := newClient(t, app)
	c.expect(c.do("POST", "/events", map[string]any{"title": "Nope", "starts_at": time.Now()}, nil), 401)

	c.signIn("host@example.org")
	ev := c.createEvent("Sommerfest 2026 im Garten")
	if !regexp.MustCompile(`^sommerfest-2026-im-garten-[a-z2-7]{6}$`).MatchString(ev.Slug) {
		t.Fatalf("slug: %s", ev.Slug)
	}
	if ev.Viewer.Role != api.ViewerRoleOwner || ev.Timezone != "Europe/Berlin" || ev.Host.DisplayName != "Host" {
		t.Fatalf("event: %+v", ev)
	}

	var got api.Event
	c.expect(c.do("GET", "/events/"+ev.Slug, nil, &got), 200)
	if got.Id != ev.Id {
		t.Fatal("get mismatch")
	}
	var list api.EventList
	c.expect(c.do("GET", "/events", nil, &list), 200)
	if len(list.Items) != 1 {
		t.Fatalf("list: %d", len(list.Items))
	}

	resp := c.do("GET", "/events/"+ev.Slug+"/qr.svg", nil, nil)
	c.expect(resp, 200)
	svg, _ := io.ReadAll(resp.Body)
	if !bytes.HasPrefix(svg, []byte("<svg")) || !bytes.Contains(svg, []byte("<rect")) {
		t.Fatalf("qr svg: %.80s", svg)
	}

	// Anonymous viewers see the event with role anonymous; unknown slugs are 404.
	anon := newClient(t, app)
	var public api.Event
	anon.expect(anon.do("GET", "/events/"+ev.Slug, nil, &public), 200)
	if public.Viewer.Role != api.ViewerRoleAnonymous {
		t.Fatalf("viewer: %+v", public.Viewer)
	}
	anon.expect(anon.do("GET", "/events/does-not-exist", nil, nil), 404)

	// Patch and delete.
	var patched api.Event
	c.expect(c.do("PATCH", "/events/"+ev.Slug, map[string]any{"guest_upload": false, "location": "Garten"}, &patched), 200)
	if patched.GuestUpload || patched.Location == nil || *patched.Location != "Garten" {
		t.Fatalf("patch: %+v", patched)
	}
	c.expect(c.do("DELETE", "/events/"+ev.Slug, nil, nil), 204)
	c.expect(c.do("GET", "/events/"+ev.Slug, nil, nil), 404)
}

func TestUploadSingleAndQueue(t *testing.T) {
	app := testutil.Start(t)
	host := newClient(t, app)
	host.signIn("host@example.org")
	ev := host.createEvent("Upload Party")

	guest := newClient(t, app)
	// No identity yet: uploads need a guest first.
	guest.expect(guest.do("POST", "/events/"+ev.Slug+"/uploads", map[string]any{"files": []map[string]any{
		{"client_id": "x", "name": "a.jpg", "size": 10, "type": "image/jpeg"}}}, nil), 401)

	var g api.Guest
	guest.expect(guest.do("POST", "/events/"+ev.Slug+"/guests", nil, &g), 200)
	var g2 api.Guest
	guest.expect(guest.do("POST", "/events/"+ev.Slug+"/guests", nil, &g2), 200)
	if g.GuestId != g2.GuestId {
		t.Fatal("ensureGuest not idempotent")
	}
	var named api.Guest
	guest.expect(guest.do("PATCH", "/events/"+ev.Slug+"/guests/me", map[string]any{"display_name": "Mia"}, &named), 200)
	if named.DisplayName == nil || *named.DisplayName != "Mia" {
		t.Fatalf("guest name: %+v", named)
	}

	// Validation: unsupported type and too large.
	guest.expect(guest.do("POST", "/events/"+ev.Slug+"/uploads", map[string]any{"files": []map[string]any{
		{"client_id": "x", "name": "a.gif", "size": 10, "type": "image/gif"}}}, nil), 415)
	guest.expect(guest.do("POST", "/events/"+ev.Slug+"/uploads", map[string]any{"files": []map[string]any{
		{"client_id": "x", "name": "a.jpg", "size": 101 << 20, "type": "image/jpeg"}}}, nil), 413)

	data := randomBytes(2048)
	item := guest.uploadSingle(ev.Slug, "IMG_0001.jpg", data)
	if item.State != api.GridItemStateQueued || !item.Processing || item.Mine == nil || !*item.Mine || item.Kind != api.GridItemKindPhoto {
		t.Fatalf("grid item: %+v", item)
	}

	raw, _ := ids.Decode(item.Id)
	var state string
	var bytesStored int64
	if err := app.Pool.QueryRow(context.Background(), "select state::text, original_bytes from media where id=$1", raw).Scan(&state, &bytesStored); err != nil {
		t.Fatal(err)
	}
	if state != "queued" || bytesStored != int64(len(data)) {
		t.Fatalf("media row: %s %d", state, bytesStored)
	}
	var jobCount int
	if err := app.Pool.QueryRow(context.Background(), "select count(*) from jobs where kind='ingest' and payload->>'media_id'=$1 and done_at is null", item.Id).Scan(&jobCount); err != nil {
		t.Fatal(err)
	}
	if jobCount != 1 {
		t.Fatalf("jobs: %d", jobCount)
	}

	// Completing twice is idempotent; another browser may not complete or abort it.
	var again api.GridItem
	guest.expect(guest.do("POST", "/uploads/"+item.Id+"/complete", nil, &again), 200)
	other := newClient(t, app)
	other.expect(other.do("POST", "/events/"+ev.Slug+"/guests", nil, nil), 200)
	other.expect(other.do("DELETE", "/uploads/"+item.Id, nil, nil), 403)

	// The event counts the processing item; mine filter shows it to the uploader only.
	var evNow api.Event
	guest.expect(guest.do("GET", "/events/"+ev.Slug, nil, &evNow), 200)
	if evNow.Counts.Processing != 1 || evNow.Counts.Photos != 1 || evNow.Viewer.Role != api.ViewerRoleGuest {
		t.Fatalf("counts/viewer: %+v %+v", evNow.Counts, evNow.Viewer)
	}
	var mine, theirs api.MediaPage
	guest.expect(guest.do("GET", "/events/"+ev.Slug+"/media?filter=mine", nil, &mine), 200)
	other.expect(other.do("GET", "/events/"+ev.Slug+"/media?filter=mine", nil, &theirs), 200)
	if len(mine.Items) != 1 || len(theirs.Items) != 0 {
		t.Fatalf("mine filter: %d %d", len(mine.Items), len(theirs.Items))
	}

	// Host review lists the guest with her name.
	var review api.HostUploads
	host.expect(host.do("GET", "/events/"+ev.Slug+"/uploads", nil, &review), 200)
	if len(review.Uploaders) != 1 || review.Uploaders[0].DisplayName != "Mia" || review.Uploaders[0].Total != 1 {
		t.Fatalf("review: %+v", review)
	}
	guest.expect(guest.do("GET", "/events/"+ev.Slug+"/uploads", nil, nil), 401)
}

func TestUploadMultipart(t *testing.T) {
	if testing.Short() {
		t.Skip("uploads 65 MiB")
	}
	app := testutil.Start(t)
	host := newClient(t, app)
	host.signIn("host@example.org")
	ev := host.createEvent("Big Files")

	size := 65 << 20
	data := randomBytes(size)
	var intents api.UploadIntentResponse
	host.expect(host.do("POST", "/events/"+ev.Slug+"/uploads", map[string]any{"files": []map[string]any{
		{"client_id": "big", "name": "big.jpg", "size": size, "type": "image/jpeg"},
	}}, &intents), 200)
	up := intents.Uploads[0]
	if up.Mode != api.UploadInitModeMultipart || up.Parts == nil || len(*up.Parts) != 9 || *up.PartSize != 8<<20 {
		t.Fatalf("intent: %+v", up)
	}
	// Upload all but the last part, then ask for status and finish with the fresh URL.
	parts := *up.Parts
	var completed []map[string]any
	for _, p := range parts[:len(parts)-1] {
		etag := putPart(t, p.Url, data[(p.PartNumber-1)*(8<<20):p.PartNumber*(8<<20)])
		completed = append(completed, map[string]any{"part_number": p.PartNumber, "etag": etag})
	}
	var status api.UploadStatus
	host.expect(host.do("GET", "/uploads/"+up.MediaId, nil, &status), 200)
	if len(status.ReceivedParts) != 8 || len(status.Parts) != 1 || status.Parts[0].PartNumber != 9 {
		t.Fatalf("status: %+v", status)
	}
	last := status.Parts[0]
	etag := putPart(t, last.Url, data[(last.PartNumber-1)*(8<<20):])
	completed = append(completed, map[string]any{"part_number": last.PartNumber, "etag": etag})

	var item api.GridItem
	host.expect(host.do("POST", "/uploads/"+up.MediaId+"/complete", map[string]any{"parts": completed}, &item), 200)
	if item.State != api.GridItemStateQueued {
		t.Fatalf("item: %+v", item)
	}
	var stored int64
	raw, _ := ids.Decode(item.Id)
	if err := app.Pool.QueryRow(context.Background(), "select original_bytes from media where id=$1", raw).Scan(&stored); err != nil {
		t.Fatal(err)
	}
	if stored != int64(size) {
		t.Fatalf("stored %d", stored)
	}
}

func putPart(t *testing.T, u string, data []byte) string {
	t.Helper()
	req, _ := http.NewRequest(http.MethodPut, u, bytes.NewReader(data))
	req.ContentLength = int64(len(data))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("upload part: %d %s", resp.StatusCode, body)
	}
	return resp.Header.Get("ETag")
}

func TestLikeToggle(t *testing.T) {
	app := testutil.Start(t)
	host := newClient(t, app)
	host.signIn("host@example.org")
	ev := host.createEvent("Likes")
	item := host.uploadSingle(ev.Slug, "a.jpg", randomBytes(512))

	anon := newClient(t, app)
	anon.expect(anon.do("PUT", "/media/"+item.Id+"/like", nil, nil), 401)

	guest := newClient(t, app)
	guest.expect(guest.do("POST", "/events/"+ev.Slug+"/guests", nil, nil), 200)
	var r1, r2, r3, r4 api.LikeResult
	guest.expect(guest.do("PUT", "/media/"+item.Id+"/like", nil, &r1), 200)
	guest.expect(guest.do("PUT", "/media/"+item.Id+"/like", nil, &r2), 200)
	host.expect(host.do("PUT", "/media/"+item.Id+"/like", nil, &r3), 200)
	if !r1.Liked || r1.LikeCount != 1 || r2.LikeCount != 1 || r3.LikeCount != 2 {
		t.Fatalf("likes: %+v %+v %+v", r1, r2, r3)
	}
	guest.expect(guest.do("DELETE", "/media/"+item.Id+"/like", nil, &r4), 200)
	if r4.Liked || r4.LikeCount != 1 {
		t.Fatalf("unlike: %+v", r4)
	}

	var detail api.MediaDetail
	host.expect(host.do("GET", "/media/"+item.Id, nil, &detail), 200)
	if !detail.Liked || detail.LikeCount != 1 || !detail.CanDelete || detail.Uploader.IsYou == nil || !*detail.Uploader.IsYou {
		t.Fatalf("detail: %+v", detail)
	}
	var guestView api.MediaDetail
	guest.expect(guest.do("GET", "/media/"+item.Id, nil, &guestView), 200)
	if guestView.Liked || guestView.CanDelete {
		t.Fatalf("guest detail: %+v", guestView)
	}

	// Removal tombstones the item and it disappears from the list.
	guest.expect(guest.do("DELETE", "/media/"+item.Id, nil, nil), 403)
	host.expect(host.do("DELETE", "/media/"+item.Id, nil, nil), 204)
	host.expect(host.do("GET", "/media/"+item.Id, nil, nil), 404)
}

func TestMediaListGrouping(t *testing.T) {
	app := testutil.Start(t)
	host := newClient(t, app)
	host.signIn("host@example.org")
	ev := host.createEvent("Grouping")
	eventID, _ := ids.Decode(ev.Id)

	berlin, _ := time.LoadLocation("Europe/Berlin")
	captured := []time.Time{
		time.Date(2026, 10, 9, 19, 30, 0, 0, berlin), // evening
		time.Date(2026, 10, 9, 20, 15, 0, 0, berlin), // evening
		time.Date(2026, 10, 9, 23, 30, 0, 0, berlin), // night
		time.Date(2026, 10, 10, 0, 30, 0, 0, berlin), // night (same group as 23:30)
		time.Date(2026, 10, 10, 9, 0, 0, 0, berlin),  // morning
	}
	for i, at := range captured {
		id := ids.New()
		_, err := app.Pool.Exec(context.Background(), `insert into media (id, event_id, kind, state, original_key, original_mime, variant_prefix, width, height, captured_at, captured_src)
			values ($1, $2, 'photo', 'ready', $3, 'image/jpeg', $4, 1000, 800, $5, 'exif')`,
			id, eventID, fmt.Sprintf("o/x/%d.jpg", i), ids.NewString(), at)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := app.Pool.Exec(context.Background(), `insert into media_variants (media_id, name, key, width, height, bytes) values ($1,'thumb',$2,256,256,1000)`,
			id, "v/"+ids.NewString()+"/thumb.webp"); err != nil {
			t.Fatal(err)
		}
	}

	var page api.MediaPage
	host.expect(host.do("GET", "/events/"+ev.Slug+"/media", nil, &page), 200)
	if len(page.Items) != 5 || page.NextCursor != nil {
		t.Fatalf("items: %d", len(page.Items))
	}
	if !page.Items[0].CapturedAt.Equal(captured[4]) || page.Items[0].Processing || page.Items[0].Variants == nil || page.Items[0].Variants.Thumb == nil {
		t.Fatalf("first item: %+v", page.Items[0])
	}
	if !strings.HasPrefix(*page.Items[0].Variants.Thumb, app.Cfg.PublicBaseURL+"/v/") {
		t.Fatalf("thumb url: %s", *page.Items[0].Variants.Thumb)
	}
	labels := []string{}
	counts := []int{}
	for _, g := range page.Groups {
		labels = append(labels, g.Label)
		counts = append(counts, g.Count)
	}
	if strings.Join(labels, ",") != "morning,night,evening" || fmt.Sprint(counts) != "[1 2 2]" {
		t.Fatalf("groups: %v %v", labels, counts)
	}
	night := page.Groups[1]
	if !night.Start.Equal(time.Date(2026, 10, 9, 22, 0, 0, 0, berlin)) || !night.End.Equal(time.Date(2026, 10, 10, 5, 0, 0, 0, berlin)) {
		t.Fatalf("night bounds: %v %v", night.Start, night.End)
	}

	// Pagination walks the whole list without duplicates.
	var seen []string
	cursor := ""
	for range 4 {
		var p api.MediaPage
		host.expect(host.do("GET", "/events/"+ev.Slug+"/media?limit=2&cursor="+url.QueryEscape(cursor), nil, &p), 200)
		for _, it := range p.Items {
			seen = append(seen, it.Id)
		}
		if p.NextCursor == nil {
			break
		}
		cursor = *p.NextCursor
	}
	if len(seen) != 5 {
		t.Fatalf("paged ids: %v", seen)
	}
	for i := range seen {
		if seen[i] != page.Items[i].Id {
			t.Fatalf("page order differs at %d", i)
		}
	}
	host.expect(host.do("GET", "/events/"+ev.Slug+"/media?cursor=nonsense", nil, nil), 400)
	var videos api.MediaPage
	host.expect(host.do("GET", "/events/"+ev.Slug+"/media?filter=videos", nil, &videos), 200)
	if len(videos.Items) != 0 {
		t.Fatal("videos filter")
	}
}

func TestSSEDeliversQueued(t *testing.T) {
	app := testutil.Start(t)
	host := newClient(t, app)
	host.signIn("host@example.org")
	ev := host.createEvent("Live")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", app.HTTP.URL+"/api/v1/events/"+ev.Slug+"/events", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if ct := resp.Header.Get("Content-Type"); !strings.HasPrefix(ct, "text/event-stream") || resp.Header.Get("X-Accel-Buffering") != "no" || resp.Header.Get("Content-Encoding") != "" {
		t.Fatalf("sse headers: %v", resp.Header)
	}
	events := make(chan string, 16)
	go func() {
		sc := bufio.NewScanner(resp.Body)
		var name string
		for sc.Scan() {
			line := sc.Text()
			switch {
			case strings.HasPrefix(line, "event: "):
				name = strings.TrimPrefix(line, "event: ")
			case strings.HasPrefix(line, "data: "):
				events <- name + " " + strings.TrimPrefix(line, "data: ")
			}
		}
	}()

	item := host.uploadSingle(ev.Slug, "live.jpg", randomBytes(256))
	select {
	case got := <-events:
		want := fmt.Sprintf(`media.queued {"id":%q,"mine":false}`, item.Id)
		if got != want {
			t.Fatalf("got %q want %q", got, want)
		}
	case <-ctx.Done():
		t.Fatal("no SSE event within timeout")
	}

	// Likes and removals are broadcast too, and Last-Event-ID replays what was missed.
	host.expect(host.do("PUT", "/media/"+item.Id+"/like", nil, nil), 200)
	select {
	case got := <-events:
		if !strings.HasPrefix(got, "like.changed ") || !strings.Contains(got, `"like_count":1`) {
			t.Fatalf("like event: %q", got)
		}
	case <-ctx.Done():
		t.Fatal("no like event")
	}
	cancel()

	req2, _ := http.NewRequest("GET", app.HTTP.URL+"/api/v1/events/"+ev.Slug+"/events", nil)
	req2.Header.Set("Last-Event-ID", "1")
	ctx2, cancel2 := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel2()
	resp2, err := http.DefaultClient.Do(req2.WithContext(ctx2))
	if err != nil {
		t.Fatal(err)
	}
	defer resp2.Body.Close()
	sc := bufio.NewScanner(resp2.Body)
	for sc.Scan() {
		if strings.HasPrefix(sc.Text(), "event: ") {
			if sc.Text() != "event: like.changed" {
				t.Fatalf("replay: %s", sc.Text())
			}
			return
		}
	}
	t.Fatal("no replayed event")
}

func TestZipAndOriginal(t *testing.T) {
	app := testutil.Start(t)
	host := newClient(t, app)
	host.signIn("host@example.org")
	ev := host.createEvent("Zip")
	a := host.uploadSingle(ev.Slug, "first.jpg", randomBytes(300))
	b := host.uploadSingle(ev.Slug, "first.jpg", randomBytes(400)) // same name: must be de-duplicated in the archive
	for _, id := range []string{a.Id, b.Id} {
		raw, _ := ids.Decode(id)
		if _, err := app.Pool.Exec(context.Background(), "update media set state='ready' where id=$1", raw); err != nil {
			t.Fatal(err)
		}
	}

	var ticket api.ZipTicket
	host.expect(host.do("POST", "/media/zip", map[string]any{"media_ids": []string{a.Id, b.Id}}, &ticket), 200)
	if ticket.Count != 2 || !strings.HasPrefix(ticket.Url, "/api/v1/zips/") {
		t.Fatalf("ticket: %+v", ticket)
	}
	resp, err := http.Get(app.HTTP.URL + ticket.Url)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 || resp.Header.Get("Content-Type") != "application/zip" || !strings.HasPrefix(resp.Header.Get("Content-Disposition"), "attachment") {
		t.Fatalf("zip response: %d %v", resp.StatusCode, resp.Header)
	}
	data, _ := io.ReadAll(resp.Body)
	zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		t.Fatalf("not a zip: %v", err)
	}
	names := []string{}
	for _, f := range zr.File {
		names = append(names, f.Name)
		rc, _ := f.Open()
		n, _ := io.Copy(io.Discard, rc)
		rc.Close()
		if n != int64(f.UncompressedSize64) || n == 0 {
			t.Fatalf("entry %s: %d bytes", f.Name, n)
		}
	}
	if strings.Join(names, ",") != "first.jpg,first-2.jpg" {
		t.Fatalf("names: %v", names)
	}
	if r, _ := http.Get(app.HTTP.URL + "/api/v1/zips/expired-token"); r.StatusCode != 404 {
		t.Fatalf("unknown token: %d", r.StatusCode)
	}

	// The original download is a 302 to a presigned URL that actually serves the bytes.
	redirect := host.do("GET", "/media/"+a.Id+"/original", nil, nil)
	host.expect(redirect, 302)
	loc := redirect.Header.Get("Location")
	if loc == "" {
		t.Fatal("no Location")
	}
	got, err := http.Get(loc)
	if err != nil {
		t.Fatal(err)
	}
	defer got.Body.Close()
	body, _ := io.ReadAll(got.Body)
	if got.StatusCode != 200 || len(body) != 300 || !strings.Contains(got.Header.Get("Content-Disposition"), "first.jpg") {
		t.Fatalf("original: %d %d %q", got.StatusCode, len(body), got.Header.Get("Content-Disposition"))
	}
}
