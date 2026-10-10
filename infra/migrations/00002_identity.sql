-- +goose Up
create table users (
  id            bytea primary key,
  email         citext unique not null,
  display_name  text not null,
  birthdate     date,
  locale        text not null default 'de',
  created_at    timestamptz not null default now()
);

create table sessions (
  token_hash    bytea primary key,
  user_id       bytea not null references users on delete cascade,
  expires_at    timestamptz not null,
  created_at    timestamptz not null default now(),
  last_seen_at  timestamptz not null default now()
);
create index on sessions (user_id);

create table magic_links (
  token_hash  bytea primary key,
  email       citext not null,
  next_path   text not null default '/',
  expires_at  timestamptz not null,
  used_at     timestamptz,
  created_at  timestamptz not null default now()
);

create table events (
  id            bytea primary key,
  slug          text unique not null,
  title         text not null,
  starts_at     timestamptz not null,
  ends_at       timestamptz,
  timezone      text not null default 'Europe/Berlin',
  location      text,
  cover_media   bytea,
  owner_id      bytea not null references users,
  guest_upload  boolean not null default true,
  guest_view    boolean not null default true,
  archived_at   timestamptz,
  created_at    timestamptz not null default now()
);
create index on events (owner_id, starts_at desc);

create table event_members (
  event_id  bytea references events on delete cascade,
  user_id   bytea references users on delete cascade,
  role      text not null check (role in ('owner','host','member')),
  created_at timestamptz not null default now(),
  primary key (event_id, user_id)
);

-- one anonymous browser identity; the cookie value is this id
create table guest_cookies (
  id          bytea primary key,
  user_id     bytea references users on delete set null,
  created_at  timestamptz not null default now()
);

-- a guest is that browser inside one event
create table guests (
  id            bytea primary key,
  event_id      bytea not null references events on delete cascade,
  cookie_id     bytea not null references guest_cookies on delete cascade,
  display_name  text,
  created_at    timestamptz not null default now(),
  unique (event_id, cookie_id)
);

-- +goose Down
drop table guests; drop table guest_cookies; drop table event_members; drop table events;
drop table magic_links; drop table sessions; drop table users;
