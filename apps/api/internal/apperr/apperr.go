// Package apperr defines the error type that handlers return and the JSON shape clients receive.
// Every error written to the wire follows the ErrorResponse schema of the OpenAPI contract.
package apperr

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
)

// Code is one of the stable error codes from the contract.
type Code string

// The error codes from ErrorResponse.error.code.
const (
	BadRequest       Code = "bad_request"
	Unauthorized     Code = "unauthorized"
	Forbidden        Code = "forbidden"
	NotFound         Code = "not_found"
	Conflict         Code = "conflict"
	TooLarge         Code = "too_large"
	UnsupportedMedia Code = "unsupported_media"
	RateLimited      Code = "rate_limited"
	Internal         Code = "internal"
)

// Error is an error with an HTTP status and a stable code.
type Error struct {
	Status  int
	Code    Code
	Message string
	Details map[string]any
}

func (e *Error) Error() string { return string(e.Code) + ": " + e.Message }

// New builds an Error for a code; the status follows from the code.
func New(code Code, msg string) *Error {
	return &Error{Status: statusFor(code), Code: code, Message: msg}
}

// WithDetails attaches extra structured information.
func (e *Error) WithDetails(d map[string]any) *Error { e.Details = d; return e }

// Convenience constructors for the common cases.
func BadRequestf(msg string) *Error { return New(BadRequest, msg) }
func Unauthorizedf(msg string) *Error {
	if msg == "" {
		msg = "sign in required"
	}
	return New(Unauthorized, msg)
}
func Forbiddenf(msg string) *Error {
	if msg == "" {
		msg = "not allowed"
	}
	return New(Forbidden, msg)
}
func NotFoundf(msg string) *Error {
	if msg == "" {
		msg = "not found"
	}
	return New(NotFound, msg)
}
func Conflictf(msg string) *Error { return New(Conflict, msg) }

func statusFor(code Code) int {
	switch code {
	case BadRequest:
		return http.StatusBadRequest
	case Unauthorized:
		return http.StatusUnauthorized
	case Forbidden:
		return http.StatusForbidden
	case NotFound:
		return http.StatusNotFound
	case Conflict:
		return http.StatusConflict
	case TooLarge:
		return http.StatusRequestEntityTooLarge
	case UnsupportedMedia:
		return http.StatusUnsupportedMediaType
	case RateLimited:
		return http.StatusTooManyRequests
	default:
		return http.StatusInternalServerError
	}
}

type wire struct {
	Error struct {
		Code    Code           `json:"code"`
		Message string         `json:"message"`
		Details map[string]any `json:"details,omitempty"`
	} `json:"error"`
}

// Write renders any error as an ErrorResponse. Unknown errors become 500 internal and are logged.
func Write(w http.ResponseWriter, r *http.Request, err error) {
	var e *Error
	if !errors.As(err, &e) {
		slog.ErrorContext(r.Context(), "unhandled error", "err", err, "path", r.URL.Path)
		e = New(Internal, "internal error")
	}
	var body wire
	body.Error.Code = e.Code
	body.Error.Message = e.Message
	body.Error.Details = e.Details
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(e.Status)
	_ = json.NewEncoder(w).Encode(body)
}
