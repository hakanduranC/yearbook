-- +goose Up
create type media_state as enum ('uploading','queued','processing','ready','failed','removed');

create table media (
  id                  bytea primary key,
  event_id            bytea references events on delete cascade,   -- null = personal library
  owner_id            bytea references users on delete set null,
  uploader_guest      bytea references guests on delete set null,
  uploader_user       bytea references users on delete set null,
  source              text not null default 'upload' check (source in ('upload','takeout','folder','picker','share')),
  kind                text not null check (kind in ('photo','video')),
  state               media_state not null default 'uploading',
  original_key        text not null,
  original_mime       text not null,
  original_filename   text,
  original_bytes      bigint,
  expected_bytes      bigint,
  multipart_upload_id text,
  variant_prefix      text not null,                 -- random public key prefix
  width               int,
  height              int,
  duration_ms         int,
  captured_at         timestamptz,
  captured_src        text check (captured_src in ('exif','filename','upload','sidecar')),
  gps                 point,
  place_name          text,
  phash               bit(64),
  content_sha256      bytea,
  dup_group_id        bytea,
  is_best_of_dup      boolean not null default true,
  processed_stages    jsonb not null default '{}'::jsonb,
  processed_at        timestamptz,
  removed_at          timestamptz,
  error               text,
  caption             text,
  caption_tsv         tsvector generated always as (to_tsvector('simple', coalesce(caption, ''))) stored,
  created_at          timestamptz not null default now()
);
create index on media (event_id, captured_at desc, id desc) where state in ('queued','processing','ready');
create index on media (event_id, state);
create index on media (owner_id, captured_at desc);
create index on media (event_id, content_sha256);
create index on media using gin (caption_tsv);

alter table events add constraint events_cover_media_fk foreign key (cover_media) references media on delete set null;

create table media_variants (
  media_id  bytea references media on delete cascade,
  name      text not null,          -- thumb | small | medium | large | poster | video
  key       text not null,
  width     int not null,
  height    int not null,
  bytes     int not null,
  primary key (media_id, name)
);

create table duplicate_groups (
  id        bytea primary key,
  event_id  bytea references events on delete cascade,
  kind      text not null check (kind in ('exact','near','burst'))
);

-- +goose Down
drop table duplicate_groups;
drop table media_variants;
alter table events drop constraint events_cover_media_fk;
drop table media;
drop type media_state;
