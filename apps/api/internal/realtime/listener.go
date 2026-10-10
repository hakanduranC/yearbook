package realtime

import (
	"context"
	"encoding/json"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"
)

// Channel is the Postgres NOTIFY channel the worker writes to.
const Channel = "media_events"

// Notification is the JSON payload the worker sends (see docs/CONVENTIONS.md).
type Notification struct {
	Type    string  `json:"type"`
	EventID *string `json:"event_id"`
	MediaID string  `json:"media_id"`
}

// Translator turns a worker notification into the SSE event name and payload to broadcast.
// Returning ok=false drops the notification (for example when the media row is gone).
type Translator func(ctx context.Context, n Notification) (name string, data any, ok bool)

// Listen holds one dedicated connection on LISTEN media_events and publishes translated events
// to the hub until ctx ends. It reconnects with backoff after errors.
func Listen(ctx context.Context, databaseURL string, hub *Hub, translate Translator) {
	backoff := time.Second
	for ctx.Err() == nil {
		err := listenOnce(ctx, databaseURL, hub, translate)
		if ctx.Err() != nil {
			return
		}
		slog.Warn("realtime: listener disconnected", "err", err, "retry_in", backoff)
		select {
		case <-time.After(backoff):
		case <-ctx.Done():
			return
		}
		if backoff < 30*time.Second {
			backoff *= 2
		}
	}
}

func listenOnce(ctx context.Context, databaseURL string, hub *Hub, translate Translator) error {
	conn, err := pgx.Connect(ctx, databaseURL)
	if err != nil {
		return err
	}
	defer conn.Close(context.Background())
	if _, err := conn.Exec(ctx, "listen "+Channel); err != nil {
		return err
	}
	slog.Info("realtime: listening", "channel", Channel)
	for {
		msg, err := conn.WaitForNotification(ctx)
		if err != nil {
			return err
		}
		var n Notification
		if err := json.Unmarshal([]byte(msg.Payload), &n); err != nil || n.EventID == nil {
			slog.Warn("realtime: bad notification", "payload", msg.Payload, "err", err)
			continue
		}
		name, data, ok := translate(ctx, n)
		if !ok {
			continue
		}
		hub.Publish(*n.EventID, name, data)
	}
}
