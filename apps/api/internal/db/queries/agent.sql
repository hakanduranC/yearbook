-- Conversations ---------------------------------------------------------------------------------

-- name: CreateConversation :one
insert into agent_conversations (id, actor, event_id, expires_at)
values ($1, $2, $3, now() + interval '30 minutes')
returning *;

-- name: GetConversation :one
select * from agent_conversations where id = $1 and actor = $2 and expires_at > now();

-- name: TouchConversation :exec
update agent_conversations
set provider_ref = $2, expires_at = now() + interval '30 minutes'
where id = $1;

-- Turns -----------------------------------------------------------------------------------------

-- name: InsertAgentTurn :exec
insert into agent_turns (id, user_id, guest_id, event_id, input, tools_used, result_kind, latency_ms, conversation_id, understood, final_call)
values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11);

-- name: GetAgentTurn :one
select * from agent_turns where id = $1;

-- Saved commands --------------------------------------------------------------------------------

-- name: CreateSavedCommand :one
insert into saved_commands (id, owner, scope, name, label, description, params, sql_template, approved_at, event_id, shared, kind, search_args)
values ($1, $2, $3, $4, $5, $6, $7, $8, now(), $9, $10, $11, $12)
returning *;

-- name: GetSavedCommand :one
select sqlc.embed(c), e.slug as event_slug
from saved_commands c
left join events e on e.id = c.event_id
where c.id = $1;

-- name: ListSavedCommands :many
-- Own commands plus the ones a host shared with every guest of the event in scope.
select sqlc.embed(c), e.slug as event_slug
from saved_commands c
left join events e on e.id = c.event_id
where (c.owner = @owner::bytea and (c.scope = 'global' or sqlc.narg('event_id')::bytea is null or c.event_id = sqlc.narg('event_id')::bytea))
   or (c.shared and c.approved_at is not null and c.event_id = sqlc.narg('event_id')::bytea)
order by c.created_at desc
limit 50;

-- name: DeleteSavedCommand :execrows
delete from saved_commands where id = $1 and owner = $2;

-- name: TouchSavedCommand :exec
update saved_commands set run_count = run_count + 1, last_run_at = now() where id = $1;
