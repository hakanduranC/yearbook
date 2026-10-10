-- name: CreateAlbum :one
insert into albums (id, event_id, owner, title, kind) values ($1, $2, $3, $4, $5) returning *;

-- name: GetAlbum :one
select * from albums where id = $1;

-- name: UpdateAlbumTitle :exec
update albums set title = $2 where id = $1;

-- name: DeleteAlbum :exec
delete from albums where id = $1;

-- name: ListEventAlbums :many
select a.*,
       (select count(*) from album_items ai where ai.album_id = a.id)::int as count,
       (select ai.media_id from album_items ai join media m on m.id = ai.media_id
          where ai.album_id = a.id and m.state = 'ready'
            and exists (select 1 from media_variants v where v.media_id = m.id and v.name = 'thumb')
          order by ai.position limit 1) as cover_media
from albums a
where a.event_id = $1
order by a.created_at desc;

-- name: AlbumCount :one
select count(*)::int from album_items where album_id = $1;

-- name: AlbumCover :one
-- The first ready item that already has a thumbnail.
select ai.media_id from album_items ai join media m on m.id = ai.media_id
where ai.album_id = $1 and m.state = 'ready'
  and exists (select 1 from media_variants v where v.media_id = m.id and v.name = 'thumb')
order by ai.position limit 1;

-- name: ListAlbumMediaIDs :many
select ai.media_id, ai.position from album_items ai
join media m on m.id = ai.media_id
where ai.album_id = $1 and m.state in ('queued','processing','ready')
order by ai.position, ai.media_id;

-- name: AlbumMaxPosition :one
select coalesce(max(position), -1)::int from album_items where album_id = $1;

-- name: AddAlbumItem :exec
insert into album_items (album_id, media_id, position) values ($1, $2, $3) on conflict do nothing;

-- name: RemoveAlbumItems :exec
delete from album_items where album_id = $1 and media_id = any(@media_ids::bytea[]);

-- name: AlbumContains :one
select exists(select 1 from album_items where album_id = $1 and media_id = $2);

-- name: CreateShare :one
insert into shares (id, album_id, created_by, expires_at, allow_download) values ($1, $2, $3, $4, $5) returning *;

-- name: GetShare :one
select * from shares where id = $1 and (expires_at is null or expires_at > now());
