package media

import (
	"testing"
	"time"

	"yearbook/api/internal/ids"
)

func TestGroups(t *testing.T) {
	berlin, _ := time.LoadLocation("Europe/Berlin")
	times := []time.Time{
		time.Date(2026, 10, 10, 9, 0, 0, 0, berlin),
		time.Date(2026, 10, 10, 0, 30, 0, 0, berlin),
		time.Date(2026, 10, 9, 23, 30, 0, 0, berlin),
		time.Date(2026, 10, 9, 20, 15, 0, 0, berlin),
		time.Date(2026, 10, 9, 4, 59, 0, 0, berlin),
	}
	groups := Groups(times, berlin)
	want := []struct {
		label string
		count int
		start time.Time
	}{
		{"morning", 1, time.Date(2026, 10, 10, 5, 0, 0, 0, berlin)},
		{"night", 2, time.Date(2026, 10, 9, 22, 0, 0, 0, berlin)},
		{"evening", 1, time.Date(2026, 10, 9, 17, 0, 0, 0, berlin)},
		{"night", 1, time.Date(2026, 10, 8, 22, 0, 0, 0, berlin)},
	}
	if len(groups) != len(want) {
		t.Fatalf("got %d groups: %+v", len(groups), groups)
	}
	for i, w := range want {
		g := groups[i]
		if g.Label != w.label || g.Count != w.count || !g.Start.Equal(w.start) {
			t.Errorf("group %d: got %s %d %v, want %s %d %v", i, g.Label, g.Count, g.Start, w.label, w.count, w.start)
		}
	}
}

func TestCursorRoundTrip(t *testing.T) {
	c := Cursor{At: time.Date(2026, 10, 9, 20, 15, 0, 123, time.UTC), ID: ids.New(), Score: 0.75}
	for _, withScore := range []bool{false, true} {
		got, err := DecodeCursor(c.Encode(withScore))
		if err != nil {
			t.Fatal(err)
		}
		if !got.At.Equal(c.At) || string(got.ID) != string(c.ID) {
			t.Fatalf("round trip lost data: %+v", got)
		}
		if withScore && got.Score != c.Score {
			t.Fatalf("score: %v", got.Score)
		}
	}
	if _, err := DecodeCursor("not-a-cursor"); err == nil {
		t.Fatal("expected error")
	}
	if c, err := DecodeCursor(""); err != nil || c.ID != nil {
		t.Fatal("empty cursor must be the start")
	}
}

func TestClassify(t *testing.T) {
	cases := map[string]struct {
		kind Kind
		ext  string
		ok   bool
	}{
		"image/jpeg":              {KindPhoto, "jpg", true},
		"video/quicktime":         {KindVideo, "mov", true},
		"IMAGE/HEIC; charset=bin": {KindPhoto, "heic", true},
		"image/gif":               {"", "", false},
	}
	for mime, want := range cases {
		kind, ext, ok := Classify(mime)
		if kind != want.kind || ext != want.ext || ok != want.ok {
			t.Errorf("%s: got %v %q %v", mime, kind, ext, ok)
		}
	}
	if PartCount(65<<20) != 9 || PartCount(8<<20) != 1 {
		t.Fatal("part count")
	}
}
