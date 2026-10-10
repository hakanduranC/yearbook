import { describe, expect, it } from 'vitest'
import {
  gridItemsOf,
  isAgentNotConfigured,
  splitAttachments,
  turnFromSearch,
  turnOf,
  viewOf,
  withResolvedItems,
} from '~/lib/agent'
import type { AgentResponse } from '~/lib/api/types'
import { item, page } from './helpers'

const base = {
  conversation_id: 'conv00000000000000000a',
  turn_id: 'turn00000000000000000a',
  understood: 'Fotos vom Abend',
  suggestions: [{ label: 'Nur Videos', text: 'nur Videos' }],
  saveable: true,
}

describe('viewOf', () => {
  it('maps media results and tracks ids without items as pending', () => {
    const v = viewOf({
      kind: 'media',
      title: 'Abend',
      media_ids: ['a', 'b', 'c'],
      items: [item({ id: 'a' })],
      group_by: 'time',
    })
    expect(v.kind).toBe('media')
    if (v.kind !== 'media') throw new Error()
    expect(v.items.map((i) => i.id)).toEqual(['a'])
    expect(v.pending).toEqual(['b', 'c'])
    expect(v.groupBy).toBe('time')
  })

  it('maps every other kind', () => {
    expect(viewOf({ kind: 'people', title: 'Wer', persons: [] })).toEqual({
      kind: 'people',
      title: 'Wer',
      persons: [],
    })
    expect(viewOf({ kind: 'stat', title: 'Fotos', value: '42' })).toEqual({
      kind: 'stat',
      title: 'Fotos',
      value: '42',
      detail: null,
      items: [],
    })
    expect(
      viewOf({ kind: 'album', album: { id: 'x', title: 'T', kind: 'manual', count: 2 } }).kind,
    ).toBe('album')
    expect(viewOf({ kind: 'clarify', question: 'Welches?', options: ['a', 'b'] })).toEqual({
      kind: 'clarify',
      question: 'Welches?',
      options: ['a', 'b'],
    })
    expect(viewOf({ kind: 'empty', title: 'Nichts' })).toEqual({ kind: 'empty', title: 'Nichts' })
  })
})

describe('turnOf', () => {
  it('carries conversation, suggestions, attachments and saveable', () => {
    const res: AgentResponse = {
      ...base,
      result: { kind: 'stat', title: 'Fotos', value: '42', detail: 'dieses Jahr' },
      attachments: [
        { name: 'chart.png', url: 'https://x/chart.png', mime: 'image/png', width: 10, height: 5 },
        { name: 'data.csv', url: 'https://x/data.csv', mime: 'text/csv' },
      ],
    }
    const turn = turnOf(res)
    expect(turn.conversationId).toBe(base.conversation_id)
    expect(turn.turnId).toBe(base.turn_id)
    expect(turn.fallback).toBe(false)
    expect(turn.attachments).toHaveLength(2)
    expect(splitAttachments(turn.attachments).images.map((a) => a.name)).toEqual(['chart.png'])
    expect(splitAttachments(turn.attachments).files.map((a) => a.name)).toEqual(['data.csv'])
  })

  it('defaults attachments to an empty list', () => {
    const turn = turnOf({ ...base, result: { kind: 'empty', title: 'Nichts' } })
    expect(turn.attachments).toEqual([])
  })
})

describe('withResolvedItems', () => {
  it('appends resolved items in the order of the pending ids and clears pending', () => {
    const turn = turnOf({
      ...base,
      result: {
        kind: 'media',
        title: 'Abend',
        media_ids: ['a', 'b', 'c'],
        items: [item({ id: 'a' })],
      },
    })
    const next = withResolvedItems(turn, [item({ id: 'c' }), item({ id: 'b' })])
    expect(gridItemsOf(next.result).map((i) => i.id)).toEqual(['a', 'b', 'c'])
    if (next.result.kind === 'media') expect(next.result.pending).toEqual([])
  })

  it('leaves non-media turns alone', () => {
    const turn = turnOf({ ...base, result: { kind: 'empty', title: 'x' } })
    expect(withResolvedItems(turn, [item({ id: 'a' })])).toBe(turn)
  })
})

describe('turnFromSearch', () => {
  it('shows search hits as a media result flagged as fallback', () => {
    const turn = turnFromSearch(
      'die Torte',
      page([item({ id: 'a' }), item({ id: 'r', state: 'removed' })]),
      'Nichts',
    )
    expect(turn.fallback).toBe(true)
    expect(turn.conversationId).toBeNull()
    expect(turn.saveable).toBe(false)
    expect(turn.understood).toBe('die Torte')
    expect(gridItemsOf(turn.result).map((i) => i.id)).toEqual(['a'])
  })

  it('shows an empty result when nothing matched', () => {
    const turn = turnFromSearch('unicorn', page([]), 'Nichts gefunden')
    expect(turn.result).toEqual({ kind: 'empty', title: 'Nichts gefunden' })
  })
})

describe('isAgentNotConfigured', () => {
  it('recognizes the 503 convention only', () => {
    expect(isAgentNotConfigured({ status: 503, message: 'agent_not_configured' })).toBe(true)
    expect(isAgentNotConfigured({ status: 503, message: 'overloaded' })).toBe(false)
    expect(isAgentNotConfigured({ status: 500, message: 'agent_not_configured' })).toBe(false)
    expect(isAgentNotConfigured(null)).toBe(false)
  })
})
