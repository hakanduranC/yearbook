// Package jobs enqueues work for the Python worker through the Postgres jobs table.
package jobs

import (
	"context"
	"encoding/json"

	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
)

// Job kinds from docs/CONVENTIONS.md ("Round 2 additions").
const (
	KindIngest          = "ingest"
	KindClusterEvent    = "cluster_event"
	KindRecomputeScores = "recompute_scores"
	KindImport          = "import"
)

// EnqueueIngest inserts an ingest job for mediaID. The payload shape is fixed by CONVENTIONS.md.
// A second call while a job is still open is a no-op thanks to the partial unique index.
func EnqueueIngest(ctx context.Context, q *db.Queries, mediaID []byte) error {
	payload, _ := json.Marshal(map[string]string{"media_id": ids.Encode(mediaID)})
	return q.EnqueueJob(ctx, db.EnqueueJobParams{Kind: KindIngest, Payload: payload})
}

// EnqueueClusterEvent asks the ML worker to recluster an event, debounced by 60 s.
func EnqueueClusterEvent(ctx context.Context, q *db.Queries, eventID []byte) error {
	return enqueueDebounced(ctx, q, KindClusterEvent, eventID)
}

// EnqueueRecomputeScores refreshes quality scores after likes changed, debounced by 60 s.
func EnqueueRecomputeScores(ctx context.Context, q *db.Queries, eventID []byte) error {
	return enqueueDebounced(ctx, q, KindRecomputeScores, eventID)
}

func enqueueDebounced(ctx context.Context, q *db.Queries, kind string, eventID []byte) error {
	if eventID == nil {
		return nil
	}
	id := ids.Encode(eventID)
	payload, _ := json.Marshal(map[string]string{"event_id": id})
	return q.EnqueueDebouncedJob(ctx, db.EnqueueDebouncedJobParams{Kind: kind, Payload: payload, EventID: id})
}

// EnqueueImport starts the light worker's import job for an imports row.
func EnqueueImport(ctx context.Context, q *db.Queries, importID []byte) error {
	payload, _ := json.Marshal(map[string]string{"import_id": ids.Encode(importID)})
	return q.EnqueueJobNow(ctx, db.EnqueueJobNowParams{Kind: KindImport, Payload: payload})
}
