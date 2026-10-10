import { queryOptions } from '@tanstack/react-query'
import { api, ok, okVoid } from '~/lib/api/client'
import type { AgentRequest, AgentResponse, MediaPage, SavedCommand } from '~/lib/api/types'
import { keys } from './keys'

export async function sendAgentMessage(body: AgentRequest): Promise<AgentResponse> {
  return ok(await api.POST('/agent/messages', { body }))
}

export function savedCommandsQuery(slug: string | null) {
  return queryOptions({
    queryKey: keys.savedCommands(slug),
    queryFn: async (): Promise<SavedCommand[]> =>
      ok(
        await api.GET('/agent/commands', {
          params: { query: slug ? { event_slug: slug } : {} },
        }),
      ).commands,
    staleTime: 60_000,
  })
}

export async function saveCommand(turn_id: string, label: string): Promise<SavedCommand> {
  return ok(await api.POST('/agent/commands', { body: { turn_id, label } }))
}

export async function deleteSavedCommand(id: string): Promise<void> {
  okVoid(await api.DELETE('/agent/commands/{command_id}', { params: { path: { command_id: id } } }))
}

export async function runSavedCommand(
  id: string,
  event_slug: string | null,
): Promise<AgentResponse> {
  return ok(
    await api.POST('/agent/commands/{command_id}/run', {
      params: { path: { command_id: id } },
      body: event_slug ? { event_slug } : {},
    }),
  )
}

/** Hybrid search without the model: the fallback when the agent is not configured. */
export async function searchMedia(slug: string | null, q: string): Promise<MediaPage> {
  if (slug) {
    return ok(await api.GET('/events/{slug}/search', { params: { path: { slug }, query: { q } } }))
  }
  return ok(await api.GET('/search', { params: { query: { q } } }))
}
