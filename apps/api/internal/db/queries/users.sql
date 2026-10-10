-- name: GetUserByEmail :one
select * from users where email = $1;

-- name: GetUserByID :one
select * from users where id = $1;

-- name: CreateUser :one
insert into users (id, email, display_name, locale)
values ($1, $2, $3, $4)
returning *;

-- name: UpdateUser :one
update users
set display_name = coalesce(sqlc.narg('display_name'), display_name),
    locale       = coalesce(sqlc.narg('locale'), locale),
    birthdate    = case when @set_birthdate::boolean then sqlc.narg('birthdate') else birthdate end
where id = $1
returning *;
