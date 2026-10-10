-- name: CreateEvent :one
insert into events (id, slug, title, starts_at, ends_at, timezone, location, owner_id)
values ($1, $2, $3, $4, $5, $6, $7, $8)
returning *;

-- name: AddEventMember :exec
insert into event_members (event_id, user_id, role) values ($1, $2, $3)
on conflict (event_id, user_id) do update set role = excluded.role;

-- name: GetEventBySlug :one
select sqlc.embed(e), u.display_name as owner_name
from events e
join users u on u.id = e.owner_id
where e.slug = $1 and e.archived_at is null;

-- name: GetEventByID :one
select sqlc.embed(e), u.display_name as owner_name
from events e
join users u on u.id = e.owner_id
where e.id = $1;

-- name: ListEventsForUser :many
select sqlc.embed(e), u.display_name as owner_name
from events e
join users u on u.id = e.owner_id
where e.archived_at is null
  and (e.owner_id = $1 or exists (select 1 from event_members m where m.event_id = e.id and m.user_id = $1))
order by e.starts_at desc;

-- name: UpdateEvent :one
update events
set title = $2, starts_at = $3, ends_at = $4, timezone = $5, location = $6,
    cover_media = $7, guest_upload = $8, guest_view = $9
where id = $1
returning *;

-- name: DeleteEvent :exec
delete from events where id = $1;

-- name: GetEventMemberRole :one
select role from event_members where event_id = $1 and user_id = $2;

-- name: GetEventCounts :one
select
  count(*) filter (where kind = 'photo' and state in ('queued','processing','ready'))::int as photos,
  count(*) filter (where kind = 'video' and state in ('queued','processing','ready'))::int as videos,
  count(*) filter (where state = 'ready')::int as ready,
  count(*) filter (where state in ('queued','processing'))::int as processing,
  count(*) filter (where state = 'failed')::int as failed,
  count(*) filter (where state in ('queued','processing','ready','failed'))::int as total
from media
where event_id = $1;
