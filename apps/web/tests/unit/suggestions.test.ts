import { describe, expect, it } from 'vitest'
import type { Suggestion } from '~/lib/api/types'
import { dismiss, parseDismissed, serializeDismissed, visibleSuggestions } from '~/lib/suggestions'

const suggestion = (id: string, is_me = false): Suggestion => ({
  person: {
    id,
    event_slug: 'sommerfest',
    face_count: 4,
    is_me,
    named: false,
    hidden: false,
  },
  event_title: 'Sommerfest',
  confidence: 0.7,
})

describe('dismiss', () => {
  it('adds without mutating and is idempotent', () => {
    const a: ReadonlySet<string> = new Set()
    const b = dismiss(a, 'p1')
    expect(a.has('p1')).toBe(false)
    expect(b.has('p1')).toBe(true)
    expect(dismiss(b, 'p1')).toBe(b)
  })
})

describe('visibleSuggestions', () => {
  it('hides dismissed and already claimed persons', () => {
    const list = [suggestion('p1'), suggestion('p2'), suggestion('p3', true)]
    expect(visibleSuggestions(list, new Set(['p2'])).map((s) => s.person.id)).toEqual(['p1'])
  })
})

describe('storage round trip', () => {
  it('serializes and parses, tolerating garbage', () => {
    const state = dismiss(dismiss(new Set(), 'a'), 'b')
    expect(parseDismissed(serializeDismissed(state))).toEqual(new Set(['a', 'b']))
    expect(parseDismissed('not json')).toEqual(new Set())
    expect(parseDismissed('{"a":1}')).toEqual(new Set())
    expect(parseDismissed('[1,"x",null]')).toEqual(new Set(['x']))
    expect(parseDismissed(null)).toEqual(new Set())
  })
})
