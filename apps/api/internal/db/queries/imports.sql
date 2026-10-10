-- name: CreateImport :one
insert into imports (id, owner_id, kind, state, event_id, source_key, source_bytes, multipart_upload_id)
values ($1, $2, $3, $4, $5, $6, $7, $8)
returning *;

-- name: GetImport :one
select * from imports where id = $1;

-- name: ListImports :many
select * from imports where owner_id = $1 order by created_at desc limit 100;

-- name: SetImportQueued :exec
update imports set state = 'queued', source_bytes = $2, multipart_upload_id = null, error = null where id = $1;

-- name: CancelImport :execrows
-- Only imports the worker has not claimed yet can be cancelled.
update imports set state = 'cancelled', finished_at = now()
where id = $1 and state in ('uploading', 'queued');

-- name: DeleteOpenImportJob :exec
delete from jobs
where kind = 'import' and payload->>'import_id' = @import_id::text and done_at is null and locked_at is null;

-- name: GetMediaForOwner :one
select * from media where id = $1 and owner_id = $2 and state <> 'removed';
