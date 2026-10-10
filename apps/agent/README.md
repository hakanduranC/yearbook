# yearbook-agent

The chat agent of Yearbook: a LangGraph loop over the Go API's MCP tools, with the structured
`present` result the UI renders (SDD §9). Python 3.12, FastAPI, LangGraph 1.x, `langchain-openai`
against the OpenAI Responses API, `langchain-mcp-adapters`, `langgraph-checkpoint-postgres`.

The service is **only called by the Go API**, which has already authenticated the viewer and
proxies `POST /api/v1/agent/messages`, `POST /api/v1/agent/commands`,
`POST /api/v1/agent/commands/{id}/run` (python kind) and `POST /api/v1/media/{id}/describe` to it.

## Run locally

```sh
eval "$(~/.local/bin/mise activate bash)"   # loads .env from the repo root
cd apps/agent
uv sync
uv run yearbook-agent serve                  # http://localhost:8091
uv run yearbook-agent eval                   # 30 cases, scripted model, in-process fake MCP + sandbox
uv run yearbook-agent eval --real            # same cases against the configured OpenAI model
uv run ruff check . && uv run pytest -q      # tests need TEST_DATABASE_URL (Postgres in Compose)
```

Without `OPENAI_API_KEY` the service starts, `GET /health` reports `configured: false`, and the
agent endpoints answer `503 {"error":{"code":"internal","message":"agent_not_configured"}}`.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | – | Without it the service runs "not configured" |
| `OPENAI_MODEL` | resolved | Empty = pick from `GET /v1/models` at startup: the newest chat-capable **gpt-6** family model (non-mini unless only mini/nano exist; realtime, audio, transcribe, tts, embedding, image, search and codex variants skipped), falling back to the newest gpt-5 family model when no gpt-6 is listed. The chosen id is logged |
| `OPENAI_BASE_URL` | – | Optional proxy / compatible endpoint |
| `MCP_URL` | `http://localhost:8080/mcp` | The Go API's MCP server |
| `SANDBOX_URL` | `http://localhost:8092` | apps/sandbox, the only thing that runs agent-written code |
| `DATABASE_URL` | – | Postgres; app tables in `public`, checkpoints in `AGENT_DB_SCHEMA` |
| `AGENT_DB_SCHEMA` | `agent` | Schema for the LangGraph checkpoint tables (created with `setup()` at startup) |
| `AGENT_PORT` | `8091` | Listen port (`serve --port` overrides) |
| `S3_ENDPOINT`, `S3_PRESIGN_ENDPOINT`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET_PRIVATE` | from `.env` | Sandbox output files go to `agent/{turn_id}/{name}` in the private bucket; attachments are 1-hour presigned GET URLs. Without S3 settings, attachments are dropped |
| `LANGSMITH_TRACING` | `false` | Set `true` together with `LANGSMITH_API_KEY` to trace every graph run; `LANGSMITH_PROJECT` defaults to `yearbook` |
| `AGENT_MAX_ROUNDS`, `AGENT_WALL_CLOCK_S` | `6`, `20` | The SDD §7.2 loop guards |
| `AGENT_CONVERSATION_TTL_MIN` | `30` | Follow-ups resume the thread for this long (sliding) |
| `AGENT_TOOL_CACHE_S` | `60` | MCP tool-schema cache per process (keyed by session token) |

## HTTP surface

All agent routes take the proxy headers the Go API sets after authenticating the request:

| Header | Meaning |
|---|---|
| `X-Actor` | 22-char id of the user, or the guest cookie id |
| `X-Actor-Kind` | `user` or `guest` (decides `agent_turns.user_id` vs `guest_id`) |
| `X-Event-Slug` | optional; the event scope. The body's `event_slug` wins when both are set |
| `X-Locale` | `de`, `en` or `tr`; the answer language |
| `X-Session-Token` | the viewer's own bearer token; forwarded unchanged to the MCP server as `Authorization: Bearer …` together with `X-Event-Slug`, so the Go side enforces visibility. The agent never uses credentials of its own |

- `POST /agent/messages` body `AgentRequest {text, event_slug?, conversation_id?}` → `AgentResponse
  {conversation_id, turn_id, understood, result, suggestions, saveable, attachments}`.
  `conversation_id` is the LangGraph thread id; a row in `agent_conversations` (`provider_ref` =
  thread id, `expires_at` = now + 30 min, refreshed per turn) decides whether a thread is resumed.
  Every turn writes an `agent_turns` row (input, tools_used, result_kind, latency_ms, understood,
  final_call, conversation_id, attachments).
- `POST /agent/commands` body `{turn_id, label}` → `201 SavedCommand`. One structured-output model
  call turns the turn's final tool call into a template (`kind` sql | search | python, `params`
  JSON schema, `sql_template` with `:param` placeholders or `search_args`); the row is approved for
  its owner, scoped to the turn's event or global.
- `POST /agent/commands/{id}/run` body `{event_slug?, params?}` → `AgentResponse` for **python**
  commands only (sql/search run inside the Go API). Permission: owner always (also unapproved);
  others only when the tool is shared, approved and in the same event.
- `POST /describe` body `{media_id, image_url, locale}` → `{text}`; the single user-initiated case
  where an image reaches the model.
- `GET /health` → `{ok, configured, model, db}`.

## How `present` is enforced

`present` is a tool with a pydantic `args_schema` (`understood` + a result discriminated on
`kind`: media, people, stat, album, clarify, empty). The graph routes a `present` call to its own
node instead of executing it, validates the arguments, and ends the turn only on success. Invalid
arguments go back to the model as a tool error (`present rejected: …`). A prose answer gets one
nudge; a second one becomes a kind `empty` result with that text as title. After 6 tool rounds or
20 s the graph writes a kind `empty` result with a locale-specific title itself. `people` and
`album` results are hydrated from the persons and albums seen in tool results during the turn.

`saveable` is true when the final tool call before `present` was `run_query`, or `search_media`
with at least two structured arguments (free text, `limit` and `order_by` do not count).

## Tools

MCP tools from the Go API (resolve_people, search_media, rank_best, list_people, describe_media,
create_album, like_media, share_album, export_zip, event_stats, run_query) are loaded per request
with the viewer's token; schemas are cached for 60 s. Local tools: `present`, and the sandbox trio
`run_python(code, inputs, media_ids?)`, `create_tool(name, description, params_schema, code)`,
`run_tool(command_id, params)`. Media ids given to `run_python` are turned into variant URLs from
tool results already seen in the turn (or one `describe_media` call) and passed to the sandbox as
`files`. Every sandbox call is logged in `sandbox_runs` (code sha256, exit code, duration).

## Prompts and evals

`src/yearbook_agent/prompts/system.md` is the system prompt template (scope, viewer first name,
claimed person, event date and timezone, today, locale, rules); `fewshots.yaml` holds the few-shot
examples in de/en/tr. `evals/cases.yaml` has 30 utterances with expected tool sequences;
`yearbook-agent eval` replays them deterministically through the real graph with the scripted
model and the fake MCP server, `--real` scores the configured model instead.

## Tests

`tests/fake_mcp.py` (FastMCP over streamable HTTP, same tool names, records forwarded headers),
`yearbook_agent/testing/fake_sandbox.py` (same `/run` contract, subprocess), a scripted chat
model. Integration tests use `TEST_DATABASE_URL` with the checkpoint schema `agent_test` and fixture
rows with random ids that are removed afterwards.

## Docker

```sh
docker build -t yearbook-agent apps/agent
docker run --env-file .env -p 8091:8091 yearbook-agent
```
