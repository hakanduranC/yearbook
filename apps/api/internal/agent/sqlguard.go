// Package agent holds the safety layers under the assistant: scoped read-only SQL through
// pg_query validation and the agent_ro role, and named-parameter binding for saved commands. The
// language-model loop itself lives in the Python service (apps/agent); Go exposes the tools over MCP.
package agent

import (
	"errors"
	"fmt"
	"strings"

	pg_query "github.com/pganalyze/pg_query_go/v6"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
)

// Views the agent may read (migration 00008). Everything else is rejected before execution; the
// agent_ro role has no other privileges anyway, the parser is the second fence.
var AllowedRelations = map[string]bool{
	"v_events": true, "v_media": true, "v_persons": true, "v_faces": true, "v_tags": true, "v_likes": true,
}

// AllowedFunctions is the function allowlist for run_query: aggregates, window functions, string,
// date and math helpers. Anything with side effects, system access or settings is absent on purpose
// (pg_sleep, current_setting, set_config, pg_read_file, dblink, lo_*, query_to_xml, ...).
var AllowedFunctions = map[string]bool{
	// aggregates
	"count": true, "sum": true, "avg": true, "min": true, "max": true, "string_agg": true, "array_agg": true,
	"json_agg": true, "jsonb_agg": true, "bool_and": true, "bool_or": true, "every": true, "percentile_cont": true,
	"percentile_disc": true, "mode": true, "stddev": true, "variance": true,
	// window
	"row_number": true, "rank": true, "dense_rank": true, "ntile": true, "lag": true, "lead": true,
	"first_value": true, "last_value": true, "nth_value": true, "percent_rank": true, "cume_dist": true,
	// null handling and comparison
	"coalesce": true, "nullif": true, "greatest": true, "least": true,
	// strings
	"lower": true, "upper": true, "initcap": true, "length": true, "char_length": true, "substring": true, "substr": true,
	"left": true, "right": true, "trim": true, "btrim": true, "ltrim": true, "rtrim": true, "concat": true,
	"concat_ws": true, "replace": true, "regexp_replace": true, "position": true, "strpos": true, "starts_with": true,
	"split_part": true, "similarity": true, "format": true, "repeat": true, "reverse": true, "md5": true,
	// numbers
	"round": true, "floor": true, "ceil": true, "ceiling": true, "abs": true, "trunc": true, "power": true, "sqrt": true,
	"mod": true, "sign": true, "width_bucket": true, "random": true,
	// dates and times
	"now": true, "date_trunc": true, "date_part": true, "extract": true, "to_char": true, "age": true, "make_date": true,
	"make_interval": true, "to_timestamp": true, "to_date": true, "justify_interval": true, "date_bin": true,
	"timezone": true, "date": true,
	// arrays and sets
	"unnest": true, "generate_series": true, "array_length": true, "cardinality": true, "array_to_string": true,
	"array_position": true, "array_remove": true,
	// json
	"json_build_object": true, "jsonb_build_object": true, "row_to_json": true, "to_json": true, "to_jsonb": true,
	// casts spelled as functions
	"int4": true, "int8": true, "float4": true, "float8": true, "numeric": true, "text": true, "bool": true,
	"timestamptz": true, "interval": true,
}

// ErrSQLRejected wraps every validation failure so callers can tell it from execution errors.
var ErrSQLRejected = errors.New("sql rejected")

// ValidateSQL parses sql with pg_query and enforces: exactly one statement, a SELECT (optionally
// with CTEs, set operations, subqueries), no INTO, no locking, only v_* relations or CTE names,
// only allowlisted functions. It returns the normalized statement text on success.
func ValidateSQL(sql string) (string, error) {
	sql = strings.TrimSpace(strings.TrimSuffix(strings.TrimSpace(sql), ";"))
	if sql == "" {
		return "", fmt.Errorf("%w: empty statement", ErrSQLRejected)
	}
	tree, err := pg_query.Parse(sql)
	if err != nil {
		return "", fmt.Errorf("%w: %v", ErrSQLRejected, err)
	}
	if len(tree.Stmts) != 1 {
		return "", fmt.Errorf("%w: exactly one statement is allowed, got %d", ErrSQLRejected, len(tree.Stmts))
	}
	stmt := tree.Stmts[0].GetStmt()
	sel := stmt.GetSelectStmt()
	if sel == nil {
		return "", fmt.Errorf("%w: only SELECT statements are allowed", ErrSQLRejected)
	}
	// CTE names are legal relation names anywhere in the statement.
	ctes := map[string]bool{}
	if err := walk(stmt.ProtoReflect(), func(m protoreflect.Message) error {
		if cte, ok := m.Interface().(*pg_query.CommonTableExpr); ok {
			ctes[strings.ToLower(cte.Ctename)] = true
		}
		return nil
	}); err != nil {
		return "", err
	}
	err = walk(stmt.ProtoReflect(), func(m protoreflect.Message) error {
		switch n := m.Interface().(type) {
		case *pg_query.SelectStmt:
			if n.IntoClause != nil {
				return fmt.Errorf("%w: SELECT INTO is not allowed", ErrSQLRejected)
			}
			if len(n.LockingClause) > 0 {
				return fmt.Errorf("%w: FOR UPDATE/SHARE is not allowed", ErrSQLRejected)
			}
		case *pg_query.RangeVar:
			name := strings.ToLower(n.Relname)
			if n.Schemaname != "" && n.Schemaname != "public" {
				return fmt.Errorf("%w: schema %q is not allowed", ErrSQLRejected, n.Schemaname)
			}
			if !AllowedRelations[name] && !ctes[name] {
				return fmt.Errorf("%w: relation %q is not available; use the v_* views: v_events, v_media, v_persons, v_faces, v_tags, v_likes", ErrSQLRejected, n.Relname)
			}
		case *pg_query.FuncCall:
			name := funcName(n)
			if !AllowedFunctions[name] {
				return fmt.Errorf("%w: function %q is not allowed", ErrSQLRejected, name)
			}
		case *pg_query.RangeTableFunc, *pg_query.RangeTableSample, *pg_query.XmlExpr, *pg_query.XmlSerialize, *pg_query.JsonTable:
			return fmt.Errorf("%w: %s is not allowed", ErrSQLRejected, string(m.Descriptor().Name()))
		case *pg_query.A_Const, *pg_query.ColumnRef, *pg_query.A_Expr, *pg_query.TypeCast, *pg_query.ResTarget:
			// plain expressions
		}
		return nil
	})
	if err != nil {
		return "", err
	}
	return sql, nil
}

// funcName returns the unqualified lowercase name of a FuncCall (pg_catalog.extract -> extract).
func funcName(f *pg_query.FuncCall) string {
	var last string
	for _, n := range f.Funcname {
		if s := n.GetString_(); s != nil {
			last = s.Sval
		}
	}
	return strings.ToLower(last)
}

// walk visits every protobuf message in the tree depth first.
func walk(m protoreflect.Message, visit func(protoreflect.Message) error) error {
	if !m.IsValid() {
		return nil
	}
	if err := visit(m); err != nil {
		return err
	}
	var walkErr error
	m.Range(func(fd protoreflect.FieldDescriptor, v protoreflect.Value) bool {
		switch {
		case fd.IsList() && fd.Kind() == protoreflect.MessageKind:
			l := v.List()
			for i := 0; i < l.Len(); i++ {
				if walkErr = walk(l.Get(i).Message(), visit); walkErr != nil {
					return false
				}
			}
		case fd.IsMap():
			// pg_query has no map fields
		case fd.Kind() == protoreflect.MessageKind:
			if walkErr = walk(v.Message(), visit); walkErr != nil {
				return false
			}
		}
		return true
	})
	return walkErr
}

var _ proto.Message = (*pg_query.Node)(nil)
