package realtime

import (
	"encoding/json"
	"sync"
)

// RingSize is how many events per event id are kept for Last-Event-ID replay.
const RingSize = 200

// Hub routes events to subscribers of one event id.
type Hub struct {
	mu     sync.Mutex
	topics map[string]*topic
}

type topic struct {
	nextID uint64
	ring   *ring
	subs   map[chan Event]struct{}
}

// NewHub creates an empty hub.
func NewHub() *Hub {
	return &Hub{topics: map[string]*topic{}}
}

func (h *Hub) topicFor(eventID string) *topic {
	t, ok := h.topics[eventID]
	if !ok {
		t = &topic{nextID: 1, ring: newRing(RingSize), subs: map[chan Event]struct{}{}}
		h.topics[eventID] = t
	}
	return t
}

// Publish sends name/data (JSON-encoded) to every subscriber of eventID and stores it for replay.
// A slow subscriber that cannot keep up is dropped rather than blocking the publisher.
func (h *Hub) Publish(eventID, name string, data any) {
	payload, err := json.Marshal(data)
	if err != nil {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	t := h.topicFor(eventID)
	e := Event{ID: t.nextID, Name: name, Data: payload}
	t.nextID++
	t.ring.add(e)
	for ch := range t.subs {
		select {
		case ch <- e:
		default:
			delete(t.subs, ch)
			close(ch)
		}
	}
}

// Subscribe registers a listener. Events newer than lastID are returned for immediate replay.
// Call cancel when the client goes away.
func (h *Hub) Subscribe(eventID string, lastID uint64) (ch <-chan Event, replay []Event, cancel func()) {
	c := make(chan Event, 64)
	h.mu.Lock()
	t := h.topicFor(eventID)
	t.subs[c] = struct{}{}
	if lastID > 0 {
		replay = t.ring.since(lastID)
	}
	h.mu.Unlock()
	cancel = func() {
		h.mu.Lock()
		defer h.mu.Unlock()
		if _, ok := t.subs[c]; ok {
			delete(t.subs, c)
			close(c)
		}
	}
	return c, replay, cancel
}
