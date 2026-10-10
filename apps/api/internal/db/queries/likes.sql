-- name: AddLike :exec
insert into likes (media_id, actor) values ($1, $2) on conflict do nothing;

-- name: RemoveLike :exec
delete from likes where media_id = $1 and actor = $2;

-- name: CountLikes :one
select count(*)::int from likes where media_id = $1;
