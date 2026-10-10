// Command ybctl is the operator CLI: migrate | seed [--fixtures DIR] | magic <email>.
package main

import (
	"context"
	"flag"
	"fmt"
	"io/fs"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"time"

	"yearbook/api/internal/auth"
	"yearbook/api/internal/config"
	"yearbook/api/internal/db"
	gendb "yearbook/api/internal/gen/db"
	"yearbook/api/internal/handlers"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/jobs"
	"yearbook/api/internal/media"
	"yearbook/api/internal/storage"
)

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, nil)))
	if len(os.Args) < 2 {
		usage()
	}
	ctx := context.Background()
	cfg, err := config.Load()
	if err != nil {
		fatal(err)
	}
	switch os.Args[1] {
	case "migrate":
		err = migrate(ctx, cfg)
	case "seed":
		fsSet := flag.NewFlagSet("seed", flag.ExitOnError)
		fixtures := fsSet.String("fixtures", "", "directory with image files to upload as queued media")
		_ = fsSet.Parse(os.Args[2:])
		err = seed(ctx, cfg, *fixtures)
	case "magic":
		if len(os.Args) < 3 {
			usage()
		}
		err = magic(ctx, cfg, os.Args[2])
	default:
		usage()
	}
	if err != nil {
		fatal(err)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: ybctl migrate | seed [--fixtures DIR] | magic <email>")
	os.Exit(2)
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "ybctl:", err)
	os.Exit(1)
}

// migrate applies infra/migrations to DATABASE_URL.
func migrate(ctx context.Context, cfg config.Config) error {
	dir, err := db.MigrationsDir()
	if err != nil {
		return err
	}
	if err := db.Migrate(ctx, cfg.DatabaseURL, dir); err != nil {
		return err
	}
	fmt.Println("migrations applied from", dir)
	return nil
}

// magic prints a fresh verify URL for email without sending mail.
func magic(ctx context.Context, cfg config.Config, email string) error {
	pool, err := db.Connect(ctx, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	defer pool.Close()
	link, err := auth.CreateMagicLink(ctx, gendb.New(pool), cfg.WebOrigin, email, "/")
	if err != nil {
		return err
	}
	fmt.Println(link)
	return nil
}

// seed creates the demo host, the demo event and optionally queued media from fixture files.
func seed(ctx context.Context, cfg config.Config, fixtures string) error {
	pool, err := db.Connect(ctx, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	defer pool.Close()
	q := gendb.New(pool)

	const email = "demo@yearbook.local"
	user, err := q.GetUserByEmail(ctx, email)
	if err != nil {
		user, err = q.CreateUser(ctx, gendb.CreateUserParams{ID: ids.New(), Email: email, DisplayName: "Demo Host", Locale: "de"})
		if err != nil {
			return fmt.Errorf("create user: %w", err)
		}
	}

	berlin, err := time.LoadLocation("Europe/Berlin")
	if err != nil {
		return err
	}
	y, m, d := time.Now().In(berlin).AddDate(0, 0, -1).Date()
	starts := time.Date(y, m, d, 18, 0, 0, 0, berlin)
	ends := starts.Add(8 * time.Hour)
	location := "Berlin"
	event, err := q.CreateEvent(ctx, gendb.CreateEventParams{
		ID: ids.New(), Slug: handlers.NewSlug("Demo Party"), Title: "Demo Party",
		StartsAt: starts, EndsAt: &ends, Timezone: "Europe/Berlin", Location: &location, OwnerID: user.ID,
	})
	if err != nil {
		return fmt.Errorf("create event: %w", err)
	}
	if err := q.AddEventMember(ctx, gendb.AddEventMemberParams{EventID: event.ID, UserID: user.ID, Role: "owner"}); err != nil {
		return err
	}

	if fixtures != "" {
		n, err := seedFixtures(ctx, cfg, q, user, event, fixtures)
		if err != nil {
			return err
		}
		fmt.Printf("uploaded %d fixture files as queued media\n", n)
	}

	link, err := auth.CreateMagicLink(ctx, q, cfg.WebOrigin, email, "/e/"+event.Slug)
	if err != nil {
		return err
	}
	fmt.Println("event:", strings.TrimRight(cfg.WebOrigin, "/")+"/e/"+event.Slug)
	fmt.Println("sign in:", link)
	return nil
}

// seedFixtures uploads every supported image or video in dir as an original and queues ingest jobs.
func seedFixtures(ctx context.Context, cfg config.Config, q *gendb.Queries, user gendb.User, event gendb.Event, dir string) (int, error) {
	store, err := storage.New(ctx, cfg)
	if err != nil {
		return 0, err
	}
	mimes := map[string]string{
		".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".heic": "image/heic",
		".heif": "image/heif", ".webp": "image/webp", ".avif": "image/avif", ".mp4": "video/mp4", ".mov": "video/quicktime",
	}
	count := 0
	err = filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		mime, ok := mimes[strings.ToLower(filepath.Ext(p))]
		if !ok {
			return nil
		}
		kind, ext, _ := media.Classify(mime)
		f, err := os.Open(p)
		if err != nil {
			return err
		}
		defer f.Close()
		st, err := f.Stat()
		if err != nil {
			return err
		}
		mediaID := ids.New()
		key := media.OriginalKey(ids.Encode(event.ID), ids.Encode(mediaID), ext)
		if err := store.Put(ctx, store.Private, key, mime, f, st.Size()); err != nil {
			return err
		}
		name := d.Name()
		size := st.Size()
		if _, err := q.CreateMedia(ctx, gendb.CreateMediaParams{
			ID: mediaID, EventID: event.ID, OwnerID: user.ID, UploaderUser: user.ID, Kind: string(kind),
			OriginalKey: key, OriginalMime: mime, OriginalFilename: &name, ExpectedBytes: &size, VariantPrefix: ids.NewString(),
		}); err != nil {
			return err
		}
		if err := q.SetMediaQueued(ctx, gendb.SetMediaQueuedParams{ID: mediaID, OriginalBytes: &size}); err != nil {
			return err
		}
		if err := jobs.EnqueueIngest(ctx, q, mediaID); err != nil {
			return err
		}
		count++
		slog.Info("seeded", "file", name, "media_id", ids.Encode(mediaID))
		return nil
	})
	return count, err
}
