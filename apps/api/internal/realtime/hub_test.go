package realtime

import "testing"

func TestRingReplay(t *testing.T) {
	r := newRing(3)
	for i := uint64(1); i <= 5; i++ {
		r.add(Event{ID: i})
	}
	got := r.since(2)
	if len(got) != 3 || got[0].ID != 3 || got[2].ID != 5 {
		t.Fatalf("since(2): %+v", got)
	}
	if len(r.since(5)) != 0 {
		t.Fatal("nothing newer than 5")
	}
}

func TestHubPublishSubscribe(t *testing.T) {
	h := NewHub()
	h.Publish("e1", "media.queued", map[string]string{"id": "a"})
	ch, replay, cancel := h.Subscribe("e1", 0)
	defer cancel()
	if len(replay) != 0 {
		t.Fatal("no replay without Last-Event-ID")
	}
	h.Publish("e1", "like.changed", map[string]int{"like_count": 1})
	h.Publish("e2", "media.removed", nil) // other event, must not arrive
	e := <-ch
	if e.ID != 2 || e.Name != "like.changed" || string(e.Data) != `{"like_count":1}` {
		t.Fatalf("event: %+v", e)
	}
	_, replay, cancel2 := h.Subscribe("e1", 1)
	defer cancel2()
	if len(replay) != 1 || replay[0].ID != 2 {
		t.Fatalf("replay: %+v", replay)
	}
}
