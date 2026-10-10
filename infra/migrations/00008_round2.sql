-- +goose Up
-- Round 2: faces, agent, albums, import. Additive; nothing from round 1 changes shape.

alter table events add column faces_enabled boolean not null default true;
alter table events add column clustered_at timestamptz;

-- analysis bookkeeping on media: light ingest is done when state=ready,
-- ML analysis (faces, embedding, quality, tags, age) is tracked separately.
alter table media add column analyzed_at timestamptz;
alter table media add column import_id bytea;
create index on media (event_id, analyzed_at) where state = 'ready';

-- identities: where the viewer-level privacy switches live
alter table identities add column hide_from_people boolean not null default false;
alter table identities add column guest_cookie_id bytea references guest_cookies on delete cascade;
create unique index on identities (guest_cookie_id) where guest_cookie_id is not null;

-- persons: cover face quality ordering and reference embeddings for cross-event suggestions
alter table persons add column cover_face_quality real;
alter table persons add column updated_at timestamptz not null default now();

-- faces: body box for age estimation, when stored
alter table faces add column body_bbox int[];

-- saved commands scoped to an event and optionally shared with its guests
alter table saved_commands add column event_id bytea references events on delete cascade;
alter table saved_commands add column shared boolean not null default false;
alter table saved_commands add column kind text not null default 'sql' check (kind in ('sql','search'));
alter table saved_commands add column search_args jsonb;
create index on saved_commands (owner, scope);
create index on saved_commands (event_id) where shared;

-- agent conversations keep the provider response id for follow-ups
create table agent_conversations (
  id            bytea primary key,
  actor         bytea not null,
  event_id      bytea references events on delete cascade,
  provider_ref  text,
  expires_at    timestamptz not null,
  created_at    timestamptz not null default now()
);
alter table agent_turns add column conversation_id bytea references agent_conversations on delete cascade;
alter table agent_turns add column understood text;
alter table agent_turns add column final_call jsonb;   -- the tool call that produced the result, for save-as-command
create index on agent_turns (conversation_id);

-- imports
create table imports (
  id            bytea primary key,
  owner_id      bytea not null references users on delete cascade,
  kind          text not null check (kind in ('takeout','zip','folder')),
  state         text not null default 'uploading' check (state in ('uploading','queued','running','done','failed','cancelled')),
  event_id      bytea references events on delete set null,
  source_key    text,            -- archive object in the private bucket, or a server path for kind=folder
  source_bytes  bigint,
  multipart_upload_id text,
  stats         jsonb not null default '{"found":0,"imported":0,"duplicates":0,"failed":0,"matched":0,"people_seeded":0}'::jsonb,
  error         text,
  created_at    timestamptz not null default now(),
  started_at    timestamptz,
  finished_at   timestamptz
);
create index on imports (owner_id, created_at desc);
alter table media add constraint media_import_fk foreign key (import_id) references imports on delete set null;

-- names Takeout attached to photos, kept until faces can be matched to them
create table media_person_hints (
  media_id  bytea references media on delete cascade,
  name      text not null,
  source    text not null default 'takeout',
  primary key (media_id, name)
);

-- read-only role and views for the agent's scoped SQL (filled by the API migration helper at startup
-- if the role does not exist; created here so RLS views can reference it)
-- +goose StatementBegin
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'agent_ro') then
    create role agent_ro nologin;
  end if;
end $$;
-- +goose StatementEnd

create or replace view v_events as
  select e.id, e.slug, e.title, e.starts_at, e.ends_at, e.timezone, e.location
  from events e
  where e.id in (
    select em.event_id from event_members em where em.user_id = decode(current_setting('app.actor', true), 'base64')
    union select e2.id from events e2 where e2.owner_id = decode(current_setting('app.actor', true), 'base64')
    union select g.event_id from guests g where g.cookie_id = decode(current_setting('app.actor', true), 'base64')
  ) or e.id = decode(current_setting('app.event', true), 'base64');

create or replace view v_media as
  select m.id, m.event_id, m.owner_id, m.kind, m.captured_at, m.captured_src, m.place_name, m.width, m.height,
         m.duration_ms, m.is_best_of_dup, m.created_at,
         coalesce(g.display_name, u.display_name) as uploader_name,
         (m.uploader_user = decode(current_setting('app.actor', true), 'base64')
          or (g.cookie_id = decode(current_setting('app.actor', true), 'base64'))) as uploaded_by_me,
         q.score, q.aesthetic, q.sharpness, q.face_count, q.eyes_open, q.smile,
         (select count(*) from likes l where l.media_id = m.id)::int as like_count,
         m.caption
  from media m
  left join guests g on g.id = m.uploader_guest
  left join users u on u.id = m.uploader_user
  left join media_quality q on q.media_id = m.id
  where m.state = 'ready'
    and (m.event_id in (select id from v_events) or m.owner_id = decode(current_setting('app.actor', true), 'base64'));

create or replace view v_persons as
  select p.id, p.event_id, p.display_name, p.face_count, p.hidden,
         pl.identity_id,
         (pl.identity_id = (select i.id from identities i where i.user_id = decode(current_setting('app.actor', true), 'base64')
                                                             or i.guest_cookie_id = decode(current_setting('app.actor', true), 'base64') limit 1)) as is_me
  from persons p
  left join person_links pl on pl.person_id = p.id
  where p.event_id in (select id from v_events);

create or replace view v_faces as
  select f.id, f.media_id, f.event_id, f.person_id, f.age_est, f.eyes_open, f.smile, f.quality
  from faces f
  where f.media_id in (select id from v_media);

create or replace view v_tags as
  select t.media_id, t.tag, t.source from media_tags t where t.media_id in (select id from v_media);

create or replace view v_likes as
  select l.media_id, l.created_at,
         (l.actor = decode(current_setting('app.actor', true), 'base64')) as by_me
  from likes l where l.media_id in (select id from v_media);

grant select on v_events, v_media, v_persons, v_faces, v_tags, v_likes to agent_ro;

-- +goose Down
revoke all on v_events, v_media, v_persons, v_faces, v_tags, v_likes from agent_ro;
drop view v_likes; drop view v_tags; drop view v_faces; drop view v_persons; drop view v_media; drop view v_events;
drop table media_person_hints;
alter table media drop constraint media_import_fk;
drop table imports;
alter table agent_turns drop column final_call, drop column understood, drop column conversation_id;
drop table agent_conversations;
alter table saved_commands drop column search_args, drop column kind, drop column shared, drop column event_id;
alter table faces drop column body_bbox;
alter table persons drop column updated_at, drop column cover_face_quality;
alter table identities drop column guest_cookie_id, drop column hide_from_people;
alter table media drop column import_id, drop column analyzed_at;
alter table events drop column clustered_at, drop column faces_enabled;
