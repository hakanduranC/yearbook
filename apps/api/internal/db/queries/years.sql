-- name: ListMyYearEvents :many
-- Events for the yearbook: the ones the user owns or is a member of, plus every event a person
-- linked to their identity appears in. Year is the event's own calendar year in its timezone.
select e.id, e.slug, e.title, e.starts_at, e.timezone, e.cover_media, e.faces_enabled,
       extract(year from e.starts_at at time zone e.timezone)::int as year,
       (select count(*) from media m where m.event_id = e.id and m.state = 'ready' and m.kind = 'photo' and m.is_best_of_dup)::int as photos,
       (select count(distinct f.media_id) from faces f
          join person_links pl on pl.person_id = f.person_id
          join media m on m.id = f.media_id
          where f.event_id = e.id and pl.identity_id = @identity_id::bytea and m.state = 'ready')::int as of_you,
       exists(select 1 from media m where m.event_id = e.id and m.state = 'ready' and m.analyzed_at is null) as analyzing
from events e
where e.archived_at is null
  and (e.owner_id = @user_id::bytea
       or exists (select 1 from event_members em where em.event_id = e.id and em.user_id = @user_id::bytea)
       or exists (select 1 from person_links pl join persons p on p.id = pl.person_id
                  where pl.identity_id = @identity_id::bytea and p.event_id = e.id))
  and (sqlc.narg('year')::int is null or extract(year from e.starts_at at time zone e.timezone)::int = sqlc.narg('year')::int)
order by e.starts_at desc;

-- name: BestMediaOfMe :many
-- Best-scored ready photos the identity appears in, in one event or one year.
select m.id, m.event_id, coalesce(q.score, -1)::real as score
from media m
join events e on e.id = m.event_id
left join media_quality q on q.media_id = m.id
where m.state = 'ready' and m.kind = 'photo' and m.is_best_of_dup
  and exists (select 1 from faces f join person_links pl on pl.person_id = f.person_id
              where f.media_id = m.id and pl.identity_id = @identity_id::bytea)
  and (sqlc.narg('event_id')::bytea is null or m.event_id = sqlc.narg('event_id')::bytea)
  and (sqlc.narg('year')::int is null or extract(year from e.starts_at at time zone e.timezone)::int = sqlc.narg('year')::int)
order by coalesce(q.score, -1) desc, coalesce(m.captured_at, m.created_at) desc, m.id
limit @row_limit;

-- name: TopPeopleForMe :many
-- People who share photos with the identity in one year, by number of shared photos. Persons of
-- the same identity across events count as one.
with mine as (
  select distinct f.media_id
  from faces f
  join person_links pl on pl.person_id = f.person_id
  join media m on m.id = f.media_id
  join events e on e.id = m.event_id
  where pl.identity_id = @identity_id::bytea and m.state = 'ready'
    and extract(year from e.starts_at at time zone e.timezone)::int = @year::int
)
select coalesce(pl2.identity_id, p.id)::bytea as key,
       (array_agg(p.id order by p.face_count desc))[1]::bytea as person_id,
       coalesce(max(p.display_name), '')::text as display_name,
       (array_agg(p.cover_face order by p.face_count desc))[1]::bytea as cover_face,
       count(distinct f.media_id)::int as count
from faces f
join mine on mine.media_id = f.media_id
join persons p on p.id = f.person_id
left join person_links pl2 on pl2.person_id = p.id
where (pl2.identity_id is null or pl2.identity_id <> @identity_id::bytea)
  and not p.hidden
group by coalesce(pl2.identity_id, p.id)
order by count desc
limit 12;

-- name: PortraitOfMe :one
-- The media item holding the best face of the identity in one year.
select f.media_id
from faces f
join person_links pl on pl.person_id = f.person_id
join media m on m.id = f.media_id
join events e on e.id = m.event_id
where pl.identity_id = @identity_id::bytea and m.state = 'ready' and m.kind = 'photo'
  and extract(year from e.starts_at at time zone e.timezone)::int = @year::int
order by f.quality desc nulls last, f.det_score desc
limit 1;
