// Package realtime fans Server-Sent Events out to browsers: an in-process hub keyed by event id,
// a replay ring per event for Last-Event-ID, and a Postgres LISTEN loop for worker notifications.
package realtime

// Event is one SSE message. ID is monotonically increasing per event.
type Event struct {
	ID   uint64
	Name string
	Data []byte
}

// ring is a fixed-size buffer of the most recent events for replay.
type ring struct {
	buf   []Event
	start int // index of the oldest entry
	n     int // number of filled entries
}

func newRing(size int) *ring {
	return &ring{buf: make([]Event, size)}
}

func (r *ring) add(e Event) {
	if r.n < len(r.buf) {
		r.buf[(r.start+r.n)%len(r.buf)] = e
		r.n++
		return
	}
	r.buf[r.start] = e
	r.start = (r.start + 1) % len(r.buf)
}

// since returns every buffered event with an id greater than lastID, oldest first.
func (r *ring) since(lastID uint64) []Event {
	var out []Event
	for i := 0; i < r.n; i++ {
		e := r.buf[(r.start+i)%len(r.buf)]
		if e.ID > lastID {
			out = append(out, e)
		}
	}
	return out
}
