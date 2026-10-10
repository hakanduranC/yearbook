// Package media holds the business rules around media items that do not touch HTTP:
// upload limits and MIME allowlist, GridItem assembly, time grouping and pagination cursors.
package media

import (
	"strings"
)

// Size limits and thresholds from the SDD.
const (
	MaxPhotoBytes    = 100 << 20 // 100 MiB
	MaxVideoBytes    = 2 << 30   // 2 GiB
	SingleMaxBytes   = 64 << 20  // below this a single presigned PUT is used
	PartSize         = 8 << 20   // multipart part size
	MaxUploadsPerReq = 20
)

// allowed maps accepted MIME types to the file extension used in object keys.
var allowed = map[string]string{
	"image/jpeg":      "jpg",
	"image/png":       "png",
	"image/heic":      "heic",
	"image/heif":      "heif",
	"image/webp":      "webp",
	"image/avif":      "avif",
	"video/mp4":       "mp4",
	"video/quicktime": "mov",
}

// Kind is photo or video.
type Kind string

// The two media kinds.
const (
	KindPhoto Kind = "photo"
	KindVideo Kind = "video"
)

// Classify validates a browser-reported MIME type and returns its kind and key extension.
// ok is false for anything outside the allowlist.
func Classify(mime string) (kind Kind, ext string, ok bool) {
	mime = strings.ToLower(strings.TrimSpace(mime))
	if i := strings.IndexByte(mime, ';'); i >= 0 {
		mime = strings.TrimSpace(mime[:i])
	}
	ext, ok = allowed[mime]
	if !ok {
		return "", "", false
	}
	if strings.HasPrefix(mime, "video/") {
		return KindVideo, ext, true
	}
	return KindPhoto, ext, true
}

// MaxBytes is the size limit for a kind.
func MaxBytes(kind Kind) int64 {
	if kind == KindVideo {
		return MaxVideoBytes
	}
	return MaxPhotoBytes
}

// OriginalKey is the private-bucket key for an original: o/{event_id}/{media_id}.{ext}.
func OriginalKey(eventID, mediaID, ext string) string {
	return "o/" + eventID + "/" + mediaID + "." + ext
}

// PartCount is the number of multipart parts for size bytes.
func PartCount(size int64) int {
	return int((size + PartSize - 1) / PartSize)
}
