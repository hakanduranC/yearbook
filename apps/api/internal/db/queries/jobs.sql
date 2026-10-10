-- name: EnqueueJob :exec
-- The partial unique index keeps one open job per (kind, media_id); a second enqueue is a no-op.
insert into jobs (kind, payload)
values ($1, $2)
on conflict (kind, (payload->>'media_id')) where done_at is null and payload ? 'media_id' do nothing;

-- name: GetOpenJobForMedia :one
select * from jobs where kind = $1 and payload->>'media_id' = $2 and done_at is null;
