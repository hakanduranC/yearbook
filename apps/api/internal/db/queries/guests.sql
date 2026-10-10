-- name: CreateGuestCookie :exec
insert into guest_cookies (id, user_id) values ($1, $2);

-- name: GuestCookieExists :one
select exists(select 1 from guest_cookies where id = $1);

-- name: LinkGuestCookieUser :exec
update guest_cookies set user_id = $2 where id = $1 and user_id is null;

-- name: UpsertGuest :one
insert into guests (id, event_id, cookie_id)
values ($1, $2, $3)
on conflict (event_id, cookie_id) do update set event_id = excluded.event_id
returning *;

-- name: GetGuest :one
select * from guests where event_id = $1 and cookie_id = $2;

-- name: UpdateGuestName :one
update guests set display_name = $2 where id = $1 returning *;
