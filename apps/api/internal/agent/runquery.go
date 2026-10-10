package agent

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Limits for run_query (docs/CONVENTIONS.md "Agent").
const (
	QueryTimeout = 2 * time.Second
	MaxRows      = 500
	MaxBytes     = 64 << 10
)

// Executor runs validated SELECTs as the agent_ro login role on a dedicated pool.
type Executor struct {
	Pool *pgxpool.Pool
}

// QueryResult is the tabular answer handed to the model.
type QueryResult struct {
	Columns   []string         `json:"columns"`
	Rows      [][]any          `json:"rows"`
	RowCount  int              `json:"row_count"`
	Truncated bool             `json:"truncated,omitempty"`
	Note      string           `json:"note,omitempty"`
	raw       []map[string]any // not sent to the model, kept for the UI
}

// Run validates sql, binds the actor and event scope and executes inside a READ ONLY transaction
// with a 2 s statement timeout. args bind $1..$n positional parameters (saved commands).
func (e *Executor) Run(ctx context.Context, actorID, eventID []byte, sql string, args ...any) (*QueryResult, error) {
	if e == nil || e.Pool == nil {
		return nil, errors.New("run_query is not available on this server")
	}
	sql, err := ValidateSQL(sql)
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, QueryTimeout+time.Second)
	defer cancel()
	tx, err := e.Pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadOnly, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return nil, fmt.Errorf("run_query: begin: %w", err)
	}
	defer tx.Rollback(context.Background()) //nolint:errcheck // read-only, rollback is the only outcome
	// SET LOCAL cannot take bind parameters; set_config can. The views decode base64 of the raw id.
	if _, err := tx.Exec(ctx, "select set_config('app.actor', $1, true), set_config('app.event', $2, true), set_config('statement_timeout', $3, true)",
		base64.StdEncoding.EncodeToString(actorID), base64.StdEncoding.EncodeToString(eventID), fmt.Sprint(QueryTimeout.Milliseconds())); err != nil {
		return nil, fmt.Errorf("run_query: scope: %w", err)
	}
	rows, err := tx.Query(ctx, sql, args...)
	if err != nil {
		return nil, friendlyPgError(err)
	}
	defer rows.Close()
	res := &QueryResult{Rows: [][]any{}}
	for _, fd := range rows.FieldDescriptions() {
		res.Columns = append(res.Columns, fd.Name)
	}
	size := 0
	for rows.Next() {
		vals, err := rows.Values()
		if err != nil {
			return nil, friendlyPgError(err)
		}
		row := make([]any, len(vals))
		for i, v := range vals {
			row[i] = jsonable(v)
		}
		enc, _ := json.Marshal(row)
		size += len(enc)
		if len(res.Rows) >= MaxRows || size > MaxBytes {
			res.Truncated = true
			res.Note = fmt.Sprintf("result capped at %d rows / %d KB; add a LIMIT or aggregate", MaxRows, MaxBytes>>10)
			break
		}
		res.Rows = append(res.Rows, row)
	}
	if err := rows.Err(); err != nil && !res.Truncated {
		return nil, friendlyPgError(err)
	}
	res.RowCount = len(res.Rows)
	return res, nil
}

// Column returns the values of one column as strings (ids come back base64url when bytea).
func (r *QueryResult) Column(name string) []any {
	for i, c := range r.Columns {
		if c == name {
			out := make([]any, 0, len(r.Rows))
			for _, row := range r.Rows {
				out = append(out, row[i])
			}
			return out
		}
	}
	return nil
}

// jsonable converts pgx values into something json.Marshal renders readably: bytea ids as
// base64url, times as RFC 3339, numerics as strings.
func jsonable(v any) any {
	switch x := v.(type) {
	case []byte:
		return base64.RawURLEncoding.EncodeToString(x)
	case time.Time:
		return x.UTC().Format(time.RFC3339)
	case fmt.Stringer:
		return x.String()
	case [16]byte:
		return base64.RawURLEncoding.EncodeToString(x[:])
	default:
		return v
	}
}

// friendlyPgError strips the driver prefix so the model sees "column x does not exist" and such.
func friendlyPgError(err error) error {
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) {
		msg := pgErr.Message
		if pgErr.Code == "57014" {
			msg = "statement timeout (2 s): narrow the query or add a LIMIT"
		}
		if pgErr.Hint != "" {
			msg += " (" + pgErr.Hint + ")"
		}
		return errors.New(msg)
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return errors.New("statement timeout (2 s): narrow the query or add a LIMIT")
	}
	return err
}

var namedParam = regexp.MustCompile(`^:([a-zA-Z_][a-zA-Z0-9_]*)`)

// BindNamed replaces :name placeholders with $n and returns the ordered values from params.
// "::type" casts and anything inside single quotes are left alone. Unknown names are an error so
// a command never runs with nulls the model did not intend.
func BindNamed(sql string, params map[string]any) (string, []any, error) {
	var b strings.Builder
	var args []any
	index := map[string]int{}
	inQuote := false
	for i := 0; i < len(sql); {
		c := sql[i]
		switch {
		case c == '\'':
			inQuote = !inQuote
		case c == ':' && !inQuote:
			if i+1 < len(sql) && sql[i+1] == ':' { // a cast
				b.WriteString("::")
				i += 2
				continue
			}
			if m := namedParam.FindStringSubmatch(sql[i:]); m != nil {
				name := m[1]
				k, ok := index[name]
				if !ok {
					v, ok := params[name]
					if !ok {
						return "", nil, fmt.Errorf("missing parameter %q", name)
					}
					args = append(args, v)
					k = len(args)
					index[name] = k
				}
				fmt.Fprintf(&b, "$%d", k)
				i += len(m[0])
				continue
			}
		}
		b.WriteByte(c)
		i++
	}
	return b.String(), args, nil
}
