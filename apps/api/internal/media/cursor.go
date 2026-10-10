package media

import (
	"encoding/base64"
	"errors"
	"strconv"
	"strings"
	"time"

	"yearbook/api/internal/ids"
)

// Cursor is the opaque position in a media listing: the sort timestamp and id of the last item,
// plus the score when the listing is ordered by score (filter=best).
type Cursor struct {
	At    time.Time
	ID    []byte
	Score float32
}

// ErrBadCursor is returned for cursors the server did not produce.
var ErrBadCursor = errors.New("media: bad cursor")

// Encode serialises the cursor as base64("unix_nanos|id[|score]").
func (c Cursor) Encode(withScore bool) string {
	s := strconv.FormatInt(c.At.UnixNano(), 10) + "|" + ids.Encode(c.ID)
	if withScore {
		s += "|" + strconv.FormatFloat(float64(c.Score), 'g', -1, 32)
	}
	return base64.RawURLEncoding.EncodeToString([]byte(s))
}

// DecodeCursor parses a cursor produced by Encode. The empty string is a valid "start" cursor.
func DecodeCursor(s string) (Cursor, error) {
	if s == "" {
		return Cursor{}, nil
	}
	raw, err := base64.RawURLEncoding.DecodeString(s)
	if err != nil {
		return Cursor{}, ErrBadCursor
	}
	parts := strings.Split(string(raw), "|")
	if len(parts) < 2 || len(parts) > 3 {
		return Cursor{}, ErrBadCursor
	}
	nanos, err := strconv.ParseInt(parts[0], 10, 64)
	if err != nil {
		return Cursor{}, ErrBadCursor
	}
	id, err := ids.Decode(parts[1])
	if err != nil {
		return Cursor{}, ErrBadCursor
	}
	c := Cursor{At: time.Unix(0, nanos).UTC(), ID: id, Score: -1}
	if len(parts) == 3 {
		f, err := strconv.ParseFloat(parts[2], 32)
		if err != nil {
			return Cursor{}, ErrBadCursor
		}
		c.Score = float32(f)
	}
	return c, nil
}
