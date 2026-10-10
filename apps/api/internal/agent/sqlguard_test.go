package agent

import (
	"strings"
	"testing"
)

func TestValidateSQL(t *testing.T) {
	ok := []string{
		"select count(*) from v_media",
		"SELECT p.display_name, count(*) FROM v_faces f JOIN v_persons p ON p.id = f.person_id GROUP BY 1 ORDER BY 2 DESC LIMIT 5;",
		"with mine as (select media_id from v_faces where person_id in (select id from v_persons where is_me)) select count(*) from mine",
		"select date_trunc('hour', captured_at) as h, count(*) from v_media group by 1",
		"select id from v_media where like_count > 2 union select media_id from v_likes where by_me",
		"select extract(year from captured_at)::int, count(*) from v_media group by 1",
		"select * from generate_series(1, 10)",
	}
	for _, q := range ok {
		if _, err := ValidateSQL(q); err != nil {
			t.Errorf("want ok: %s\n  %v", q, err)
		}
	}
	bad := map[string]string{
		"delete from v_media":                                      "only SELECT",
		"select 1; select 2":                                       "exactly one statement",
		"select * from media":                                      `relation "media"`,
		"select * from v_media, users":                             `relation "users"`,
		"select pg_sleep(5)":                                       `function "pg_sleep"`,
		"select current_setting('app.actor')":                      `function "current_setting"`,
		"select * into tmp from v_media":                           "SELECT INTO",
		"select * from v_media for update":                         "FOR UPDATE",
		"select * from public.v_media, pg_catalog.pg_roles":        `schema "pg_catalog"`,
		"create table x as select 1":                               "only SELECT",
		"select * from v_media where id in (select id from faces)": `relation "faces"`,
		"copy (select 1) to stdout":                                "only SELECT",
		"explain select * from v_media":                            "only SELECT",
	}
	for q, want := range bad {
		_, err := ValidateSQL(q)
		if err == nil {
			t.Errorf("want rejection: %s", q)
			continue
		}
		if !strings.Contains(err.Error(), want) {
			t.Errorf("%s: want %q in %v", q, want, err)
		}
	}
}

func TestBindNamed(t *testing.T) {
	sql, args, err := BindNamed("select * from v_media where like_count >= :min and kind = :kind and id <> :min::text limit :n", map[string]any{"min": 2, "kind": "photo", "n": 10})
	if err != nil {
		t.Fatal(err)
	}
	if sql != "select * from v_media where like_count >= $1 and kind = $2 and id <> $1::text limit $3" || len(args) != 3 || args[2] != 10 {
		t.Fatalf("got %q %v", sql, args)
	}
	if _, _, err := BindNamed("select :missing", map[string]any{}); err == nil {
		t.Fatal("missing parameter must fail")
	}
	sql, args, err = BindNamed("select 'a:b', captured_at::date from v_media", nil)
	if err != nil || sql != "select 'a:b', captured_at::date from v_media" || len(args) != 0 {
		t.Fatalf("quotes and casts untouched: %q %v %v", sql, args, err)
	}
}
