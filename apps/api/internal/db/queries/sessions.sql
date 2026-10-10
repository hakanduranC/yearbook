-- name: CreateSession :exec
insert into sessions (token_hash, user_id, expires_at) values ($1, $2, $3);

-- name: GetSessionUser :one
select u.*, s.last_seen_at as session_last_seen_at
from sessions s
join users u on u.id = s.user_id
where s.token_hash = $1 and s.expires_at > now();

-- name: TouchSession :exec
update sessions
set last_seen_at = now(), expires_at = now() + interval '90 days'
where token_hash = $1;

-- name: DeleteSession :exec
delete from sessions where token_hash = $1;

-- name: CreateMagicLink :exec
insert into magic_links (token_hash, email, next_path, expires_at) values ($1, $2, $3, $4);

-- name: ConsumeMagicLink :one
update magic_links
set used_at = now()
where token_hash = $1 and used_at is null and expires_at > now()
returning email, next_path;
