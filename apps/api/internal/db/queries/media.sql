-- name: CreateMedia :one
insert into media (id, event_id, owner_id, uploader_guest, uploader_user, kind, state,
                   original_key, original_mime, original_filename, expected_bytes, multipart_upload_id, variant_prefix)
values ($1, $2, $3, $4, $5, $6, 'uploading', $7, $8, $9, $10, $11, $12)
returning *;

-- name: GetMedia :one
select * from media where id = $1;

-- name: FindReadyDuplicate :one
select id from media
where event_id = $1 and content_sha256 = $2 and state = 'ready'
order by created_at
limit 1;

-- name: SetMediaQueued :exec
update media
set state = 'queued', original_bytes = $2, multipart_upload_id = null, error = null
where id = $1;

-- name: SetMediaFailed :exec
update media set state = 'failed', error = $2 where id = $1;

-- name: SetMediaRequeued :exec
update media set state = 'queued', error = null where id = $1;

-- name: DeleteMediaRow :exec
delete from media where id = $1;

-- name: RemoveMedia :exec
update media set state = 'removed', removed_at = now() where id = $1;

-- name: GetEventCoverFallback :one
-- Newest ready photo of an event, used as the cover when none is set.
select m.id from media m
where m.event_id = $1 and m.state = 'ready' and m.kind = 'photo' and m.is_best_of_dup
order by coalesce(m.captured_at, m.created_at) desc, m.id desc
limit 1;

-- name: GetVariants :many
select * from media_variants where media_id = $1;

-- name: ListMediaIDs :many
-- One listing query for every filter of GET /events/{slug}/media. Unused filter parameters are null.
--   filter: all | videos | mine | me | person | album | library
--   person_id / album_id: the id after "person:" / "album:"
--   identity_id: the viewer's identity (for me)
--   age_min / age_max: at least one face whose age (exact via a linked identity's birthdate,
--   else faces.age_est) lies in the range
select m.id, coalesce(m.captured_at, m.created_at)::timestamptz as sort_at
from media m
where ((@filter::text <> 'library' and m.event_id = @event_id)
    or (@filter::text = 'library' and m.event_id is null and m.owner_id = @user_id::bytea))
  and m.state in ('queued','processing','ready')
  and (@filter::text <> 'videos' or m.kind = 'video')
  and (@filter::text <> 'mine' or (m.uploader_user = @user_id::bytea or m.uploader_guest = @guest_id::bytea))
  and (@filter::text <> 'me' or exists (
        select 1 from faces f join person_links pl on pl.person_id = f.person_id
        where f.media_id = m.id and pl.identity_id = @identity_id::bytea))
  and (@filter::text <> 'person' or exists (
        select 1 from faces f where f.media_id = m.id and f.person_id = @person_id::bytea))
  and (@filter::text <> 'album' or exists (
        select 1 from album_items ai where ai.media_id = m.id and ai.album_id = @album_id::bytea))
  and (@filter::text in ('mine','person','album') or m.is_best_of_dup)
  and ((sqlc.narg('age_min')::int is null and sqlc.narg('age_max')::int is null) or exists (
        select 1 from faces f
        left join person_links pl on pl.person_id = f.person_id
        left join identities i on i.id = pl.identity_id
        where f.media_id = m.id
          and coalesce(
                case when i.birthdate is not null and m.captured_at is not null
                     then extract(year from age(m.captured_at, i.birthdate))::real end,
                f.age_est) between coalesce(sqlc.narg('age_min')::int, 0) and coalesce(sqlc.narg('age_max')::int, 200)))
  and (@cursor_id::bytea is null or (coalesce(m.captured_at, m.created_at), m.id) < (@cursor_at::timestamptz, @cursor_id::bytea))
order by coalesce(m.captured_at, m.created_at) desc, m.id desc
limit @row_limit;

-- name: ListMediaIDsBest :many
-- Highlights: score order, one per duplicate group (is_best_of_dup), at most three per 30-minute
-- window. The window rank is computed over the whole event so pages stay consistent.
with ranked as (
  select m.id, coalesce(m.captured_at, m.created_at)::timestamptz as sort_at, coalesce(q.score, -1)::real as score,
         row_number() over (
           partition by date_bin('30 minutes', coalesce(m.captured_at, m.created_at), timestamptz '2000-01-01')
           order by coalesce(q.score, -1) desc, m.id) as slot
  from media m
  left join media_quality q on q.media_id = m.id
  where m.event_id = @event_id
    and m.state = 'ready'
    and m.is_best_of_dup
)
select r.id, r.sort_at, r.score
from ranked r
where r.slot <= 3
  and (@cursor_id::bytea is null or (r.score, r.sort_at, r.id) < (@cursor_score::real, @cursor_at::timestamptz, @cursor_id::bytea))
order by r.score desc, r.sort_at desc, r.id desc
limit @row_limit;

-- name: ListLibraryIDs :many
-- The signed-in user's own media: imports and uploads, optionally only those without an event.
select m.id, coalesce(m.captured_at, m.created_at)::timestamptz as sort_at
from media m
where m.owner_id = @owner_id
  and m.state in ('queued','processing','ready')
  and (not @unassigned::boolean or m.event_id is null)
  and (@cursor_id::bytea is null or (coalesce(m.captured_at, m.created_at), m.id) < (@cursor_at::timestamptz, @cursor_id::bytea))
order by coalesce(m.captured_at, m.created_at) desc, m.id desc
limit @row_limit;

-- name: GetGridRows :many
-- One row per media id with everything a GridItem or MediaDetail needs.
-- actor is the liker identity (user id or guest cookie id); user_id and guest_id identify the viewer
-- as uploader; identity_id marks items the viewer appears in (me).
select
  m.id, m.event_id, m.kind, m.state, m.captured_at, m.captured_src, m.created_at,
  m.width, m.height, m.duration_ms, m.original_filename, m.place_name,
  m.uploader_guest, m.uploader_user, m.analyzed_at,
  coalesce(g.display_name, u.display_name, '')::text as uploader_name,
  q.score,
  coalesce((select json_object_agg(v.name, v.key) from media_variants v where v.media_id = m.id), '{}'::json)::jsonb as variants,
  (select count(*) from likes l where l.media_id = m.id)::int as like_count,
  exists(select 1 from likes l where l.media_id = m.id and l.actor = @actor::bytea) as liked,
  coalesce((m.uploader_user is not null and m.uploader_user = @user_id::bytea)
    or (m.uploader_guest is not null and m.uploader_guest = @guest_id::bytea), false)::boolean as mine,
  exists(select 1 from faces f join person_links pl on pl.person_id = f.person_id
         where f.media_id = m.id and pl.identity_id = @identity_id::bytea) as me,
  coalesce((select array_agg(distinct f.person_id) from faces f where f.media_id = m.id and f.person_id is not null), '{}')::bytea[] as person_ids
from media m
left join guests g on g.id = m.uploader_guest
left join users u on u.id = m.uploader_user
left join media_quality q on q.media_id = m.id
where m.id = any(@ids::bytea[]);

-- name: ListMediaForZip :many
select m.id, m.event_id, m.owner_id, m.kind, m.state, m.original_key, m.original_mime, m.original_filename,
       coalesce((select v.key from media_variants v where v.media_id = m.id and v.name = 'large'), '')::text as large_key
from media m
where m.id = any(@ids::bytea[]) and m.state = 'ready';

-- name: ListHostUploads :many
select m.id, m.kind, m.state, m.error, m.created_at, m.uploader_guest, m.uploader_user,
       m.original_filename, m.original_bytes,
       coalesce(g.display_name, u.display_name, '')::text as uploader_name,
       coalesce((select v.key from media_variants v where v.media_id = m.id and v.name = 'thumb'), '')::text as thumb_key
from media m
left join guests g on g.id = m.uploader_guest
left join users u on u.id = m.uploader_user
where m.event_id = $1 and m.state <> 'removed'
order by m.created_at desc;

-- name: SetMediaEvent :exec
-- Moves an item between the library and an event; faces follow so clustering sees them.
update media set event_id = $2 where id = $1;

-- name: SetFacesEvent :exec
update faces set event_id = $2, person_id = null where media_id = $1;

-- name: ListMediaByIDs :many
select * from media where id = any(@ids::bytea[]) and state <> 'removed';

-- name: ListMediaTags :many
select tag, source from media_tags where media_id = $1 order by source, tag limit 50;
