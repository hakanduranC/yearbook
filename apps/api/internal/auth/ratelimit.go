package auth

import (
	"sync"
	"time"

	"golang.org/x/time/rate"
)

// KeyedLimiter keeps one token bucket per key (an email or an IP) and forgets idle keys.
type KeyedLimiter struct {
	mu      sync.Mutex
	limit   rate.Limit
	burst   int
	entries map[string]*limiterEntry
	lastGC  time.Time
}

type limiterEntry struct {
	lim  *rate.Limiter
	seen time.Time
}

// NewKeyedLimiter allows `events` events per `window` for each key.
func NewKeyedLimiter(events int, window time.Duration) *KeyedLimiter {
	return &KeyedLimiter{
		limit:   rate.Every(window / time.Duration(events)),
		burst:   events,
		entries: map[string]*limiterEntry{},
		lastGC:  time.Now(),
	}
}

// Allow reports whether one more event is permitted for key right now.
func (k *KeyedLimiter) Allow(key string) bool {
	k.mu.Lock()
	defer k.mu.Unlock()
	now := time.Now()
	if now.Sub(k.lastGC) > 10*time.Minute {
		for key, e := range k.entries {
			if now.Sub(e.seen) > 2*time.Hour {
				delete(k.entries, key)
			}
		}
		k.lastGC = now
	}
	e, ok := k.entries[key]
	if !ok {
		e = &limiterEntry{lim: rate.NewLimiter(k.limit, k.burst)}
		k.entries[key] = e
	}
	e.seen = now
	return e.lim.Allow()
}

// MagicLinkLimits are the two buckets from the SDD: 5 per hour per email, 20 per hour per IP.
type MagicLinkLimits struct {
	PerEmail *KeyedLimiter
	PerIP    *KeyedLimiter
}

// NewMagicLinkLimits builds the default limiters.
func NewMagicLinkLimits() MagicLinkLimits {
	return MagicLinkLimits{
		PerEmail: NewKeyedLimiter(5, time.Hour),
		PerIP:    NewKeyedLimiter(20, time.Hour),
	}
}
