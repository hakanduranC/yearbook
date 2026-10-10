// Package ids creates and encodes the 16-byte random identifiers used for every public id.
// Wire format is base64url without padding (always 22 characters); database columns are bytea.
package ids

import (
	"crypto/rand"
	"encoding/base64"
	"errors"
)

// Len is the number of raw bytes in an id.
const Len = 16

// ErrInvalid is returned by Decode for anything that is not a 22-character base64url id.
var ErrInvalid = errors.New("ids: invalid id")

// New returns 16 fresh random bytes.
func New() []byte {
	b := make([]byte, Len)
	rand.Read(b) // crypto/rand never returns an error on supported platforms (Go 1.24+).
	return b
}

// Encode turns raw bytes into the 22-character wire form.
func Encode(b []byte) string {
	return base64.RawURLEncoding.EncodeToString(b)
}

// Decode parses the wire form back into 16 raw bytes.
func Decode(s string) ([]byte, error) {
	if len(s) != 22 {
		return nil, ErrInvalid
	}
	b, err := base64.RawURLEncoding.DecodeString(s)
	if err != nil || len(b) != Len {
		return nil, ErrInvalid
	}
	return b, nil
}

// NewString is New followed by Encode.
func NewString() string {
	return Encode(New())
}
