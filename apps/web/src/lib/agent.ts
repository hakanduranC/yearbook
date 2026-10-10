import type {
  AgentResponse,
  AgentResult,
  Album,
  Attachment,
  Chip,
  GridItem,
  MediaPage,
  Person,
} from '~/lib/api/types'

/** What the UI renders. `items` are resolved grid items; `pending` ids still need a fetch. */
export type AgentView =
  | {
      kind: 'media'
      title: string
      items: GridItem[]
      pending: string[]
      groupBy: 'time' | 'person' | 'none'
    }
  | { kind: 'people'; title: string; persons: Person[] }
  | { kind: 'stat'; title: string; value: string; detail: string | null; items: GridItem[] }
  | { kind: 'album'; album: Album }
  | { kind: 'clarify'; question: string; options: string[] }
  | { kind: 'empty'; title: string }

export interface AgentTurn {
  conversationId: string | null
  turnId: string | null
  understood: string
  result: AgentView
  suggestions: Chip[]
  /** Images or files the agent produced; short-lived URLs, never cached. */
  attachments: Attachment[]
  saveable: boolean
  /** True when the model was not available and plain search answered instead. */
  fallback: boolean
}

export function viewOf(result: AgentResult): AgentView {
  switch (result.kind) {
    case 'media': {
      const items = result.items ?? []
      const have = new Set(items.map((i) => i.id))
      return {
        kind: 'media',
        title: result.title,
        items,
        pending: result.media_ids.filter((id) => !have.has(id)),
        groupBy: result.group_by ?? 'none',
      }
    }
    case 'people':
      return { kind: 'people', title: result.title, persons: result.persons }
    case 'stat':
      return {
        kind: 'stat',
        title: result.title,
        value: result.value,
        detail: result.detail ?? null,
        items: result.items ?? [],
      }
    case 'album':
      return { kind: 'album', album: result.album }
    case 'clarify':
      return { kind: 'clarify', question: result.question, options: result.options }
    case 'empty':
      return { kind: 'empty', title: result.title }
  }
}

export function turnOf(response: AgentResponse): AgentTurn {
  return {
    conversationId: response.conversation_id,
    turnId: response.turn_id,
    understood: response.understood,
    result: viewOf(response.result),
    suggestions: response.suggestions,
    attachments: response.attachments ?? [],
    saveable: response.saveable,
    fallback: false,
  }
}

/** The fallback when the agent is not configured: a plain search page shown as a media result. */
export function turnFromSearch(q: string, page: MediaPage, emptyTitle: string): AgentTurn {
  const items = page.items.filter((i) => i.state !== 'removed')
  return {
    conversationId: null,
    turnId: null,
    understood: q,
    result:
      items.length === 0
        ? { kind: 'empty', title: emptyTitle }
        : { kind: 'media', title: q, items, pending: [], groupBy: 'none' },
    suggestions: [],
    attachments: [],
    saveable: false,
    fallback: true,
  }
}

/** Fills resolved items into a media turn, keeping the order of the original ids. */
export function withResolvedItems(turn: AgentTurn, resolved: GridItem[]): AgentTurn {
  if (turn.result.kind !== 'media') return turn
  const byId = new Map(resolved.map((i) => [i.id, i]))
  const items = [...turn.result.items]
  for (const id of turn.result.pending) {
    const item = byId.get(id)
    if (item) items.push(item)
  }
  return { ...turn, result: { ...turn.result, items, pending: [] } }
}

/** `503 {code: internal, message: agent_not_configured}` per the conventions. */
export function isAgentNotConfigured(error: unknown): boolean {
  const e = error as { status?: number; message?: string } | null
  return e?.status === 503 && /agent_not_configured/.test(e.message ?? '')
}

/** Items a turn can show in a grid, whatever the kind. */
export function gridItemsOf(view: AgentView): GridItem[] {
  if (view.kind === 'media' || view.kind === 'stat') return view.items
  return []
}

export function isMediaKind(view: AgentView): view is Extract<AgentView, { kind: 'media' }> {
  return view.kind === 'media'
}

export function isImageAttachment(a: Attachment): boolean {
  return a.mime.startsWith('image/')
}

/** Images first (they render as tiles), then everything else (a download row). */
export function splitAttachments(list: readonly Attachment[]): {
  images: Attachment[]
  files: Attachment[]
} {
  return {
    images: list.filter(isImageAttachment),
    files: list.filter((a) => !isImageAttachment(a)),
  }
}
