-- +goose Up
create table persons (
  id            bytea primary key,
  event_id      bytea not null references events on delete cascade,
  display_name  text,
  cover_face    bytea,
  face_count    int not null default 0,
  centroid      vector(512),
  hidden        boolean not null default false,
  created_at    timestamptz not null default now()
);
create index on persons (event_id, face_count desc);

create table faces (
  id          bytea primary key,
  media_id    bytea not null references media on delete cascade,
  event_id    bytea references events on delete cascade,
  person_id   bytea references persons on delete set null,
  bbox        int[] not null,
  landmarks   real[],
  det_score   real not null,
  quality     real,
  embedding   vector(512) not null,
  age_est     real,
  age_est_sd  real,
  eyes_open   real,
  smile       real,
  crop_key    text,
  created_at  timestamptz not null default now()
);
create index on faces (event_id, person_id);
create index on faces (media_id);
create index on faces using hnsw (embedding vector_cosine_ops);

create table person_constraints (
  event_id    bytea not null references events on delete cascade,
  face_a      bytea not null references faces on delete cascade,
  face_b      bytea not null references faces on delete cascade,
  kind        text not null check (kind in ('must_link','cannot_link')),
  created_by  bytea,
  created_at  timestamptz not null default now(),
  primary key (face_a, face_b)
);

create table identities (
  id            bytea primary key,
  user_id       bytea unique references users on delete cascade,
  display_name  text not null,
  birthdate     date,
  link_across   boolean not null default true,
  created_at    timestamptz not null default now()
);

create table person_links (
  person_id     bytea primary key references persons on delete cascade,
  identity_id   bytea not null references identities on delete cascade,
  confirmed_by  bytea,
  confidence    real,
  created_at    timestamptz not null default now()
);
create index on person_links (identity_id);

-- +goose Down
drop table person_links; drop table identities; drop table person_constraints; drop table faces; drop table persons;
