-- +goose Up
create table jobs (
  id            bigserial primary key,
  kind          text not null,
  payload       jsonb not null default '{}'::jsonb,
  priority      int not null default 0,
  run_after     timestamptz not null default now(),
  attempts      int not null default 0,
  max_attempts  int not null default 5,
  locked_by     text,
  locked_at     timestamptz,
  done_at       timestamptz,
  error         text,
  created_at    timestamptz not null default now()
);
create index jobs_ready_idx on jobs (priority desc, run_after, id) where done_at is null;
create unique index jobs_one_per_media_idx on jobs (kind, (payload->>'media_id')) where done_at is null and payload ? 'media_id';

-- +goose StatementBegin
create function jobs_notify() returns trigger language plpgsql as $$
begin
  perform pg_notify('jobs_new', new.kind);
  return new;
end $$;
-- +goose StatementEnd
create trigger jobs_notify_insert after insert on jobs for each row execute function jobs_notify();

-- +goose Down
drop trigger jobs_notify_insert on jobs;
drop function jobs_notify();
drop table jobs;
