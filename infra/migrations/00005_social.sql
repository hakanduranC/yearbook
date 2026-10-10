-- +goose Up
create table likes (
  media_id    bytea references media on delete cascade,
  actor       bytea not null,                 -- user id or guest_cookie id
  created_at  timestamptz not null default now(),
  primary key (media_id, actor)
);

create table albums (
  id          bytea primary key,
  event_id    bytea references events on delete cascade,
  owner       bytea not null,
  title       text not null,
  kind        text not null check (kind in ('highlights','manual','agent')),
  created_at  timestamptz not null default now()
);
create table album_items (
  album_id  bytea references albums on delete cascade,
  media_id  bytea references media on delete cascade,
  position  int not null,
  primary key (album_id, media_id)
);
create table shares (
  id              bytea primary key,
  album_id        bytea references albums on delete cascade,
  created_by      bytea not null,
  expires_at      timestamptz,
  allow_download  boolean not null default true,
  created_at      timestamptz not null default now()
);

-- +goose Down
drop table shares; drop table album_items; drop table albums; drop table likes;
