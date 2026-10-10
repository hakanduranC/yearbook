-- +goose Up
create table media_embeddings (
  media_id   bytea primary key references media on delete cascade,
  model      text not null,
  embedding  vector(1152) not null
);
create index on media_embeddings using hnsw (embedding vector_cosine_ops);

create table media_quality (
  media_id    bytea primary key references media on delete cascade,
  sharpness   real,
  exposure    real,
  aesthetic   real,
  face_count  int,
  eyes_open   real,
  smile       real,
  score       real
);

create table media_tags (
  media_id  bytea references media on delete cascade,
  tag       text not null,
  source    text not null,
  primary key (media_id, tag, source)
);
create index on media_tags using gin (tag gin_trgm_ops);

create table saved_commands (
  id            bytea primary key,
  owner         bytea not null,
  scope         text not null check (scope in ('event','global')),
  name          text not null,
  label         text not null,
  description   text not null,
  params        jsonb not null,
  sql_template  text not null,
  approved_at   timestamptz,
  created_at    timestamptz not null default now()
);

create table agent_turns (
  id           bytea primary key,
  user_id      bytea,
  guest_id     bytea,
  event_id     bytea,
  input        text not null,
  tools_used   jsonb not null default '[]'::jsonb,
  result_kind  text,
  latency_ms   int,
  created_at   timestamptz not null default now()
);

-- +goose Down
drop table agent_turns; drop table saved_commands; drop table media_tags; drop table media_quality; drop table media_embeddings;
