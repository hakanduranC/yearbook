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

-- name: GetVariants :many
select * from media_variants where media_id = $1;

-- name: ListMediaIDs :many
select m.id, coalesce(m.captured_at, m.created_at)::timestamptz as sort_at
from media m
where m.event_id = @event_id
  and m.state in ('queued','processing','ready')
  and (@filter::text <> 'videos' or m.kind = 'video')
  and (@filter::text <> 'mine' or (m.uploader_user = @user_id or m.uploader_guest = @guest_id))
  and (@filter::text = 'mine' or m.is_best_of_dup)
  and (@cursor_id::bytea is null or (coalesce(m.captured_at, m.created_at), m.id) < (@cursor_at::timestamptz, @cursor_id::bytea))
order by coalesce(m.captured_at, m.created_at) desc, m.id desc
limit @row_limit;

-- name: ListMediaIDsBest :many
select m.id, coalesce(m.captured_at, m.created_at)::timestamptz as sort_at, coalesce(q.score, -1)::real as score
from media m
left join media_quality q on q.media_id = m.id
where m.event_id = @event_id
  and m.state in ('queued','processing','ready')
  and m.is_best_of_dup
  and (@cursor_id::bytea is null or (coalesce(q.score, -1), coalesce(m.captured_at, m.created_at), m.id) < (@cursor_score::real, @cursor_at::timestamptz, @cursor_id::bytea))
order by coalesce(q.score, -1) desc, coalesce(m.captured_at, m.created_at) desc, m.id desc
limit @row_limit;

-- name: GetGridRows :many
-- One row per media id with everything a GridItem or MediaDetail needs.
-- actor is the liker identity (user id or guest cookie id); user_id and guest_id identify the viewer as uploader.
select
  m.id, m.event_id, m.kind, m.state, m.captured_at, m.captured_src, m.created_at,
  m.width, m.height, m.duration_ms, m.original_filename, m.place_name,
  m.uploader_guest, m.uploader_user,
  coalesce(g.display_name, u.display_name, '')::text as uploader_name,
  q.score,
  coalesce((select json_object_agg(v.name, v.key) from media_variants v where v.media_id = m.id), '{}'::json)::jsonb as variants,
  (select count(*) from likes l where l.media_id = m.id)::int as like_count,
  exists(select 1 from likes l where l.media_id = m.id and l.actor = @actor::bytea) as liked,
  coalesce((m.uploader_user is not null and m.uploader_user = @user_id::bytea)
    or (m.uploader_guest is not null and m.uploader_guest = @guest_id::bytea), false)::boolean as mine
from media m
left join guests g on g.id = m.uploader_guest
left join users u on u.id = m.uploader_user
left join media_quality q on q.media_id = m.id
where m.id = any(@ids::bytea[]);

-- name: ListMediaForZip :many
select m.id, m.event_id, m.kind, m.state, m.original_key, m.original_mime, m.original_filename,
       coalesce((select v.key from media_variants v where v.media_id = m.id and v.name = 'large'), '')::text as large_key
from media m
where m.id = any(@ids::bytea[]) and m.state = 'ready';

-- name: ListHostUploads :many
select m.id, m.kind, m.state, m.error, m.created_at, m.uploader_guest, m.uploader_user,
       coalesce(g.display_name, u.display_name, '')::text as uploader_name,
       coalesce((select v.key from media_variants v where v.media_id = m.id and v.name = 'thumb'), '')::text as thumb_key
from media m
left join guests g on g.id = m.uploader_guest
left join users u on u.id = m.uploader_user
where m.event_id = $1 and m.state <> 'removed'
order by m.created_at desc;
