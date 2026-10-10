// Package jobs enqueues work for the Python worker through the Postgres jobs table.
package jobs

import (
	"context"
	"encoding/json"

	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
)

// KindIngest is the job the worker runs after an upload completes.
const KindIngest = "ingest"

// EnqueueIngest inserts an ingest job for mediaID. The payload shape is fixed by CONVENTIONS.md.
// A second call while a job is still open is a no-op thanks to the partial unique index.
func EnqueueIngest(ctx context.Context, q *db.Queries, mediaID []byte) error {
	payload, _ := json.Marshal(map[string]string{"media_id": ids.Encode(mediaID)})
	return q.EnqueueJob(ctx, db.EnqueueJobParams{Kind: KindIngest, Payload: payload})
}
