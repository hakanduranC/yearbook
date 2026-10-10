-- +goose Up
-- Agent-created tools: code the agent wrote, run only inside the sandbox service.
alter table saved_commands drop constraint if exists saved_commands_kind_check;
alter table saved_commands add constraint saved_commands_kind_check check (kind in ('sql','search','python'));
alter table saved_commands add column code text;                      -- python source for kind = python
alter table saved_commands add column runtime text not null default 'python3.12';
alter table saved_commands add column created_by_agent boolean not null default false;
alter table saved_commands add column run_count int not null default 0;
alter table saved_commands add column last_run_at timestamptz;

-- what a turn produced besides the structured result (charts, collages), as presigned-able object keys
alter table agent_turns add column attachments jsonb not null default '[]'::jsonb;

-- every sandbox execution is logged
create table sandbox_runs (
  id            bytea primary key,
  turn_id       bytea,
  command_id    bytea references saved_commands on delete set null,
  actor         bytea not null,
  code_sha256   bytea not null,
  exit_code     int,
  duration_ms   int,
  stdout_bytes  int,
  error         text,
  created_at    timestamptz not null default now()
);
create index on sandbox_runs (actor, created_at desc);

-- +goose Down
drop table sandbox_runs;
alter table agent_turns drop column attachments;
alter table saved_commands drop column last_run_at, drop column run_count, drop column created_by_agent, drop column runtime, drop column code;
alter table saved_commands drop constraint saved_commands_kind_check;
alter table saved_commands add constraint saved_commands_kind_check check (kind in ('sql','search'));
