-- name: EnqueueJob :exec
-- The partial unique index keeps one open job per (kind, media_id); a second enqueue is a no-op.
insert into jobs (kind, payload)
values ($1, $2)
on conflict (kind, (payload->>'media_id')) where done_at is null and payload ? 'media_id' do nothing;

-- name: GetOpenJobForMedia :one
select * from jobs where kind = $1 and payload->>'media_id' = $2 and done_at is null;

-- name: EnqueueDebouncedJob :exec
-- One open job per (kind, event_id), delayed 60 s so bursts of changes collapse (CONVENTIONS.md).
insert into jobs (kind, payload, run_after)
select @kind, @payload, now() + interval '60 seconds'
where not exists (select 1 from jobs where kind = @kind and payload->>'event_id' = @event_id::text and done_at is null);

-- name: EnqueueJobNow :exec
insert into jobs (kind, payload) values ($1, $2);
