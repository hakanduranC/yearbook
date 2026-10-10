-- Identities -------------------------------------------------------------------------------

-- name: GetIdentityForActor :one
-- The identity of a signed-in user or of a guest cookie (whichever is given).
select * from identities
where (@user_id::bytea is not null and user_id = @user_id::bytea)
   or (@cookie_id::bytea is not null and guest_cookie_id = @cookie_id::bytea)
order by (user_id is not null) desc
limit 1;

-- name: CreateIdentity :one
insert into identities (id, user_id, guest_cookie_id, display_name, birthdate)
values ($1, $2, $3, $4, $5)
returning *;

-- name: UpdateIdentitySettings :exec
update identities
set display_name     = coalesce(sqlc.narg('display_name'), display_name),
    birthdate        = case when @set_birthdate::boolean then sqlc.narg('birthdate') else birthdate end,
    link_across      = coalesce(sqlc.narg('link_across'), link_across),
    hide_from_people = coalesce(sqlc.narg('hide_from_people'), hide_from_people)
where id = $1;

-- name: IdentityHasClaim :one
select exists(select 1 from person_links where identity_id = $1);

-- Persons ----------------------------------------------------------------------------------

-- name: ListPersons :many
-- Persons of an event, biggest first. Hidden persons (own flag or identity flag) are omitted
-- unless they belong to the viewer's identity.
select p.id, p.event_id, p.display_name, p.cover_face, p.face_count, p.hidden, p.created_at,
       pl.identity_id,
       coalesce(pl.identity_id = @identity_id::bytea, false)::boolean as is_me,
       (select count(distinct f.media_id) from faces f where f.person_id = p.id)::int as media_count
from persons p
left join person_links pl on pl.person_id = p.id
left join identities i on i.id = pl.identity_id
where p.event_id = @event_id
  and p.face_count > 0
  and ((not p.hidden and not coalesce(i.hide_from_people, false)) or pl.identity_id = @identity_id::bytea)
order by p.face_count desc, p.created_at, p.id;

-- name: GetPersonRow :one
select p.id, p.event_id, p.display_name, p.cover_face, p.face_count, p.hidden, p.created_at,
       pl.identity_id,
       coalesce(pl.identity_id = @identity_id::bytea, false)::boolean as is_me,
       (select count(distinct f.media_id) from faces f where f.person_id = p.id)::int as media_count
from persons p
left join person_links pl on pl.person_id = p.id
where p.id = @person_id;

-- name: GetPerson :one
select * from persons where id = $1;

-- name: GetPersonLink :one
select * from person_links where person_id = $1;

-- name: UpdatePersonName :exec
update persons set display_name = $2, updated_at = now() where id = $1;

-- name: UpdatePersonHidden :exec
update persons set hidden = $2, updated_at = now() where id = $1;

-- name: CreatePerson :one
insert into persons (id, event_id, display_name, cover_face, cover_face_quality, face_count)
values ($1, $2, $3, $4, $5, $6)
returning *;

-- name: DeletePerson :exec
delete from persons where id = $1;

-- name: RecomputePerson :exec
-- Refreshes face_count, cover face (best quality) and centroid after faces moved.
update persons p
set face_count = (select count(*) from faces f where f.person_id = p.id),
    cover_face = (select f.id from faces f where f.person_id = p.id order by f.quality desc nulls last, f.det_score desc limit 1),
    cover_face_quality = (select f.quality from faces f where f.person_id = p.id order by f.quality desc nulls last, f.det_score desc limit 1),
    centroid = (select avg(f.embedding) from faces f where f.person_id = p.id),
    updated_at = now()
where p.id = $1;

-- name: SuggestedMeCandidates :many
-- Persons ranked by how often they appear in media the viewer uploaded (the "Is this you?" heuristic).
select f.person_id, count(*)::int as n
from faces f
join media m on m.id = f.media_id
join persons p on p.id = f.person_id
where f.event_id = @event_id
  and f.person_id is not null
  and not p.hidden
  and ((@user_id::bytea is not null and m.uploader_user = @user_id::bytea)
    or (@guest_id::bytea is not null and m.uploader_guest = @guest_id::bytea))
group by f.person_id
order by n desc
limit 2;

-- name: EventAnalyzing :one
select exists(select 1 from media where event_id = $1 and state = 'ready' and analyzed_at is null);

-- name: EventPeopleCounts :one
select
  (select count(*) from persons p
     left join person_links pl on pl.person_id = p.id
     left join identities i on i.id = pl.identity_id
     where p.event_id = @event_id and p.face_count > 0 and not p.hidden and not coalesce(i.hide_from_people, false))::int as people,
  (select count(*) from media m where m.event_id = @event_id and m.state = 'ready' and m.analyzed_at is not null)::int as faces_done,
  (select count(distinct f.media_id) from faces f
     join person_links pl on pl.person_id = f.person_id
     join media m on m.id = f.media_id
     where f.event_id = @event_id and m.state = 'ready' and pl.identity_id = @identity_id::bytea)::int as of_you;

-- Links -------------------------------------------------------------------------------------

-- name: UpsertPersonLink :exec
insert into person_links (person_id, identity_id, confirmed_by, confidence)
values ($1, $2, $3, 1.0)
on conflict (person_id) do update set identity_id = excluded.identity_id, confirmed_by = excluded.confirmed_by, created_at = now();

-- name: DeletePersonLink :exec
delete from person_links where person_id = $1;

-- name: ListMyPersons :many
-- Persons linked to an identity across events, newest event first.
select p.id, p.event_id, p.display_name, p.cover_face, p.face_count, p.hidden, p.created_at,
       pl.identity_id, true::boolean as is_me,
       (select count(distinct f.media_id) from faces f where f.person_id = p.id)::int as media_count,
       e.slug as event_slug
from persons p
join person_links pl on pl.person_id = p.id
join events e on e.id = p.event_id
where pl.identity_id = $1
order by e.starts_at desc, p.face_count desc;

-- Faces -------------------------------------------------------------------------------------

-- name: GetFace :one
select * from faces where id = $1;

-- name: ListFacesForMedia :many
select f.id, f.media_id, f.person_id, f.bbox, f.quality, f.age_est, f.crop_key
from faces f
where f.media_id = $1
order by f.det_score desc, f.id;

-- name: ListFacesOfPerson :many
select id, media_id, quality, det_score from faces where person_id = $1 order by quality desc nulls last, det_score desc;

-- name: MoveFacesToPerson :exec
update faces set person_id = @to_person where person_id = any(@from_persons::bytea[]);

-- name: AssignFacesToPerson :execrows
update faces set person_id = @to_person where id = any(@face_ids::bytea[]) and person_id = @from_person;

-- name: DetachFace :exec
update faces set person_id = null where id = $1;

-- name: AddPersonConstraint :exec
insert into person_constraints (event_id, face_a, face_b, kind, created_by)
values ($1, $2, $3, $4, $5)
on conflict (face_a, face_b) do update set kind = excluded.kind, created_by = excluded.created_by, created_at = now();

-- name: ListPersonConstraints :many
select * from person_constraints where event_id = $1 order by created_at;

-- Cross-event suggestions ----------------------------------------------------------------------

-- name: ListMySuggestions :many
-- Reference set: up to 30 best faces of the identity's claimed persons. Candidates: unclaimed,
-- visible persons in the user's events where the identity has no claimed person yet, with
-- max cosine similarity >= 0.45 to any reference face. Capture years and age estimates come back
-- so the caller can apply the age-consistency rule when a birthdate is known.
with ref as (
  select f.embedding, m.captured_at
  from faces f
  join person_links pl on pl.person_id = f.person_id
  join media m on m.id = f.media_id
  where pl.identity_id = @identity_id
  order by f.quality desc nulls last, f.det_score desc
  limit 30
),
my_events as (
  select e.id from events e
  where e.archived_at is null
    and (e.owner_id = @user_id
      or exists (select 1 from event_members em where em.event_id = e.id and em.user_id = @user_id)
      or exists (select 1 from guests g join guest_cookies gc on gc.id = g.cookie_id where g.event_id = e.id and gc.user_id = @user_id))
),
cand as (
  select p.id, p.event_id
  from persons p
  where p.event_id in (select id from my_events)
    and p.face_count > 0 and not p.hidden
    and not exists (select 1 from person_links pl where pl.person_id = p.id)
    and not exists (select 1 from person_links pl2 join persons p2 on p2.id = pl2.person_id
                    where pl2.identity_id = @identity_id and p2.event_id = p.event_id)
),
scored as (
  select c.id as person_id, c.event_id,
         max(1 - (f.embedding <=> r.embedding))::real as similarity,
         coalesce(avg(f.age_est), -1)::real as age_est,
         coalesce(avg(extract(year from m.captured_at)), -1)::real as cand_year,
         coalesce(avg(extract(year from age(m.captured_at, sqlc.narg('birthdate')::date))), -1)::real as exact_age
  from cand c
  join faces f on f.person_id = c.id
  join media m on m.id = f.media_id
  cross join ref r
  group by c.id, c.event_id
)
select s.person_id, s.event_id, s.similarity, s.age_est, s.cand_year, s.exact_age,
       (select coalesce(avg(extract(year from captured_at)), -1)::real from ref)::real as ref_year,
       e.slug as event_slug, e.title as event_title, e.starts_at as event_starts_at
from scored s
join events e on e.id = s.event_id
where s.similarity >= 0.45
order by s.similarity desc
limit 50;

-- Face data deletion ------------------------------------------------------------------------------

-- name: ListFacesOfIdentity :many
select f.id, f.crop_key, f.event_id, f.person_id
from faces f
join person_links pl on pl.person_id = f.person_id
where pl.identity_id = $1;

-- name: DeleteFacesOfIdentity :exec
delete from faces f
using person_links pl
where pl.person_id = f.person_id and pl.identity_id = $1;

-- name: DeletePersonsOfIdentity :exec
delete from persons p using person_links pl where pl.person_id = p.id and pl.identity_id = $1;

-- name: ListEventSlugsForIDs :many
select id, slug from events where id = any(@ids::bytea[]);
