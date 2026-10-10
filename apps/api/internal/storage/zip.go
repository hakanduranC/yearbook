package storage

import (
	"archive/zip"
	"context"
	"fmt"
	"io"
	"time"
)

// ZipEntry is one file to stream into an archive.
type ZipEntry struct {
	Bucket string
	Key    string
	Name   string
}

// StreamZip writes a store-only zip of the entries to w, fetching each object as it goes.
// Images are already compressed, so Store keeps CPU and latency low.
func (c *Client) StreamZip(ctx context.Context, w io.Writer, entries []ZipEntry) error {
	zw := zip.NewWriter(w)
	for _, e := range entries {
		if err := c.addEntry(ctx, zw, e); err != nil {
			return err
		}
	}
	return zw.Close()
}

func (c *Client) addEntry(ctx context.Context, zw *zip.Writer, e ZipEntry) error {
	body, _, err := c.Get(ctx, e.Bucket, e.Key)
	if err != nil {
		return err
	}
	defer body.Close()
	fw, err := zw.CreateHeader(&zip.FileHeader{Name: e.Name, Method: zip.Store, Modified: time.Now()})
	if err != nil {
		return fmt.Errorf("storage: zip header: %w", err)
	}
	if _, err := io.Copy(fw, body); err != nil {
		return fmt.Errorf("storage: zip copy %s: %w", e.Key, err)
	}
	return nil
}
