// Minimal in-memory stand-in for the Go API, used by Playwright and for local SSR checks.
// Usage: node tests/e2e/mock-api.mjs [port]
//
// Sessions: a `yb_session` cookie with any value signs the caller in as the seeded member (owner
// of both events). Guests get a `yb_guest` cookie from POST /events/{slug}/guests.
// Test controls: POST /__mock/reset re-seeds everything; POST /__mock/agent?configured=0|1 toggles
// the 503 agent_not_configured answer.

import { randomBytes } from 'node:crypto'
import { createServer } from 'node:http'

const port = Number(process.argv[2] ?? process.env.MOCK_API_PORT ?? 8089)
const origin = `http://localhost:${port}`
const id = () => randomBytes(16).toString('base64url')
const now = () => new Date().toISOString()

export const SLUG = 'demo-party-abc123'
export const SLUG2 = 'sommerfest-xyz789'
const variants = (key) => ({
  thumb: `${origin}/img/${key}/thumb.webp`,
  small: `${origin}/img/${key}/small.webp`,
  medium: `${origin}/img/${key}/medium.webp`,
  large: `${origin}/img/${key}/large.webp`,
})
const crop = (faceId) => `${origin}/api/v1/faces/${faceId}/crop.jpg`

// ------------------------------------------------------------------ state
let S
let agentConfigured = true

function seed() {
  const stableId = (name) => name.padEnd(22, '0').slice(0, 22)
  const events = {
    [SLUG]: {
      id: stableId('evt1'),
      slug: SLUG,
      title: 'Annas Dreißigster',
      starts_at: '2026-06-14T18:00:00Z',
      ends_at: null,
      timezone: 'Europe/Berlin',
      location: 'Kantine Fabrik',
      cover: variants('cover'),
      host: { display_name: 'Mert' },
      guest_upload: true,
      guest_view: true,
      faces_enabled: true,
      clustered_at: '2026-06-15T02:00:00Z',
      created_at: '2026-06-01T00:00:00Z',
    },
    [SLUG2]: {
      id: stableId('evt2'),
      slug: SLUG2,
      title: 'Sommerfest im Hof',
      starts_at: '2026-08-22T15:00:00Z',
      ends_at: null,
      timezone: 'Europe/Berlin',
      location: 'Hinterhof',
      cover: variants('cover2'),
      host: { display_name: 'Hakan' },
      guest_upload: true,
      guest_view: true,
      faces_enabled: true,
      clustered_at: null,
      created_at: '2026-08-01T00:00:00Z',
    },
  }

  const persons = [
    person('per1', SLUG, { display_name: 'Anna', named: true, face_count: 12, media_count: 11 }),
    person('per2', SLUG, {
      display_name: null,
      named: false,
      face_count: 5,
      media_count: 5,
      suggested_me: true,
    }),
    person('per3', SLUG, { display_name: 'Mert', named: true, face_count: 8, media_count: 7 }),
    person('per4', SLUG, { display_name: null, named: false, face_count: 3, media_count: 3 }),
    person('per5', SLUG2, { display_name: 'Lea', named: true, face_count: 6, media_count: 6 }),
    person('per6', SLUG2, { display_name: null, named: false, face_count: 4, media_count: 4 }),
  ]
  function person(key, slug, extra) {
    return {
      id: stableId(key),
      event_slug: slug,
      crop_url: crop(stableId(`face-${key}`)),
      is_me: false,
      linked: false,
      hidden: false,
      can_edit: true,
      ...extra,
    }
  }

  const base = (key, captured_at, extra = {}) => ({
    id: stableId(key),
    kind: 'photo',
    state: 'ready',
    captured_at,
    captured_src: 'exif',
    width: 4032,
    height: 3024,
    duration_ms: null,
    variants: variants(key),
    like_count: 0,
    liked: false,
    mine: false,
    person_ids: [],
    score: null,
    processing: false,
    analyzed: true,
    ...extra,
  })
  const P = (k) => stableId(k)
  const media = [
    {
      event: SLUG,
      ...base('p1', '2026-06-14T21:40:00Z', {
        like_count: 3,
        score: 0.91,
        person_ids: [P('per1'), P('per2')],
      }),
    },
    {
      event: SLUG,
      ...base('p2', '2026-06-14T21:10:00Z', {
        like_count: 1,
        score: 0.84,
        person_ids: [P('per2'), P('per3')],
      }),
    },
    {
      event: SLUG,
      ...base('p3', '2026-06-14T20:05:00Z', {
        kind: 'video',
        duration_ms: 65_000,
        poster: `${origin}/img/p3/poster.webp`,
        video_url: `${origin}/img/p3/video.mp4`,
        score: 0.5,
      }),
    },
    {
      event: SLUG,
      ...base('p4', '2026-06-14T17:30:00Z', {
        score: 0.77,
        person_ids: [P('per1'), P('per3'), P('per4')],
      }),
    },
    {
      event: SLUG,
      ...base('p5', '2026-06-14T17:05:00Z', {
        like_count: 2,
        score: 0.72,
        person_ids: [P('per2')],
      }),
    },
    {
      event: SLUG,
      ...base('p6', '2026-06-14T16:20:00Z', { score: 0.61, person_ids: [P('per1')] }),
    },
    {
      event: SLUG,
      ...base('p7', '2026-06-14T16:02:00Z', { score: 0.42, person_ids: [P('per2'), P('per4')] }),
    },
    { event: SLUG, ...base('p8', '2026-06-14T15:40:00Z', { score: 0.3, person_ids: [P('per3')] }) },
    {
      event: SLUG2,
      ...base('q1', '2026-08-22T16:00:00Z', { score: 0.8, person_ids: [P('per5'), P('per6')] }),
    },
    {
      event: SLUG2,
      ...base('q2', '2026-08-22T17:30:00Z', { score: 0.7, person_ids: [P('per6')] }),
    },
    { event: SLUG2, ...base('q3', '2026-08-22T19:10:00Z', { score: 0.6 }) },
    { event: null, ...base('l1', '2025-12-24T18:00:00Z', { captured_src: 'sidecar' }) },
    { event: null, ...base('l2', '2025-12-24T18:10:00Z', { captured_src: 'sidecar' }) },
    { event: null, ...base('l3', '2026-01-01T00:05:00Z', { captured_src: 'sidecar' }) },
  ]

  const faces = []
  for (const m of media) {
    m.person_ids.forEach((pid, i) => {
      faces.push({
        id: stableId(`f-${m.id.slice(0, 4)}-${i}`),
        media_id: m.id,
        person_id: pid,
        bbox: [100 + i * 300, 200, 220, 260],
        quality: 0.8,
        age_est: 30,
      })
    })
  }

  const albums = [
    {
      id: stableId('alb-high'),
      event_slug: SLUG,
      title: 'Highlights',
      kind: 'highlights',
      item_ids: [P('p1'), P('p2'), P('p4')],
      cover: variants('p1'),
      can_edit: true,
      allow_download: true,
    },
    {
      id: stableId('alb-cake'),
      event_slug: SLUG,
      title: 'Die Torte',
      kind: 'manual',
      item_ids: [P('p5'), P('p6')],
      cover: variants('p5'),
      can_edit: true,
      allow_download: true,
    },
  ]
  const shares = new Map([
    [stableId('share1'), { album_id: stableId('alb-high'), allow_download: true }],
    [stableId('share2'), { album_id: stableId('alb-cake'), allow_download: false }],
  ])
  const commands = [
    {
      id: stableId('cmd1'),
      name: 'group_shots',
      label: 'Gruppenfotos',
      description: 'Die besten Fotos mit mindestens drei Personen',
      scope: 'event',
      event_slug: SLUG,
      params: {},
      shared: true,
      kind: 'search',
      created_by_agent: false,
      run_count: 4,
    },
    {
      id: stableId('cmd2'),
      name: 'who_with_me',
      label: 'Mit wem am meisten',
      description: 'Zählt gemeinsame Fotos pro Person über das Jahr',
      scope: 'global',
      params: {},
      shared: false,
      kind: 'python',
      created_by_agent: true,
      run_count: 1,
    },
  ]
  const imports = [
    {
      id: stableId('imp-old'),
      kind: 'takeout',
      state: 'done',
      stats: {
        found: 120,
        imported: 104,
        duplicates: 14,
        failed: 2,
        matched: 61,
        people_seeded: 3,
      },
      error: null,
      created_at: '2026-09-01T10:00:00Z',
      finished_at: '2026-09-01T10:12:00Z',
    },
  ]
  S = {
    events,
    persons,
    media,
    faces,
    albums,
    shares,
    commands,
    imports,
    me: {
      id: stableId('user1'),
      email: 'hakan@example.com',
      display_name: 'Hakan',
      locale: 'de',
      link_across: true,
      hide_from_people: false,
      birthdate: undefined,
    },
    uploads: new Map(),
    guests: new Map(),
    conversations: new Map(),
  }
}
seed()

// ------------------------------------------------------------------ helpers
const sseClients = new Set()
let sseId = 0
function send(res, status, body, headers = {}) {
  const json = JSON.stringify(body)
  res.writeHead(status, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(json),
    ...headers,
  })
  res.end(json)
}
function error(res, status, code, message) {
  send(res, status, { error: { code, message } })
}
function cookies(req) {
  return Object.fromEntries(
    (req.headers.cookie ?? '')
      .split(';')
      .map((c) => c.trim().split('='))
      .filter((p) => p[0]),
  )
}
function broadcast(name, data) {
  sseId += 1
  const frame = `id: ${sseId}\nevent: ${name}\ndata: ${JSON.stringify(data)}\n\n`
  for (const res of sseClients) res.write(frame)
}
async function body(req) {
  const chunks = []
  for await (const c of req) chunks.push(c)
  const text = Buffer.concat(chunks).toString('utf8')
  return text ? JSON.parse(text) : {}
}
const pixel = Buffer.from(
  '/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=',
  'base64',
)

const claimedIds = () => new Set(S.persons.filter((p) => p.is_me).map((p) => p.id))
function gridItem(m) {
  const mine = claimedIds()
  const { event: _e, ...rest } = m
  return { ...rest, me: m.person_ids.some((pid) => mine.has(pid)) }
}
function eventCounts(slug) {
  const items = S.media.filter((m) => m.event === slug)
  const mine = claimedIds()
  return {
    photos: items.filter((m) => m.kind === 'photo').length,
    videos: items.filter((m) => m.kind === 'video').length,
    ready: items.filter((m) => m.state === 'ready').length,
    processing: items.filter((m) => m.state !== 'ready').length,
    failed: 0,
    of_you: items.filter((m) => m.person_ids.some((pid) => mine.has(pid))).length,
    people: S.persons.filter((p) => p.event_slug === slug && !p.hidden).length,
    faces_done: slug === SLUG2 ? 2 : items.length,
  }
}
function eventFor(slug, viewer) {
  const e = S.events[slug]
  return { ...e, counts: eventCounts(slug), viewer }
}
const groupsFor = (slug) =>
  slug === SLUG
    ? [
        { label: 'night', start: '2026-06-14T20:00:00Z', end: '2026-06-15T03:00:00Z', count: 3 },
        { label: 'evening', start: '2026-06-14T15:00:00Z', end: '2026-06-14T20:00:00Z', count: 5 },
      ]
    : [{ label: 'afternoon', start: '2026-08-22T09:00:00Z', end: '2026-08-22T15:00:00Z', count: 3 }]
const albumOut = (a) => ({
  id: a.id,
  event_slug: a.event_slug,
  title: a.title,
  kind: a.kind,
  count: a.item_ids.length,
  cover: S.media.find((m) => m.id === a.item_ids[0])?.variants ?? a.cover,
  can_edit: a.can_edit,
})
const albumDetail = (a, allow = a.allow_download) => ({
  ...albumOut(a),
  items: a.item_ids
    .map((mid) => S.media.find((m) => m.id === mid))
    .filter(Boolean)
    .map(gridItem),
  allow_download: allow,
  event_title: S.events[a.event_slug]?.title,
})
function eventSummary(slug) {
  const mine = claimedIds()
  const ofYou = S.media.filter((m) => m.event === slug && m.person_ids.some((p) => mine.has(p)))
  const e = S.events[slug]
  return {
    slug,
    title: e.title,
    starts_at: e.starts_at,
    photos: S.media.filter((m) => m.event === slug).length,
    of_you: ofYou.length,
    cover: e.cover,
    of_you_items: ofYou.slice(0, 4).map(gridItem),
    analyzing: slug === SLUG2,
  }
}
function agentAnswer(text, slug) {
  const inEvent = (m) => (slug ? m.event === slug : m.event !== undefined)
  const items = S.media.filter(inEvent).map(gridItem)
  const persons = S.persons.filter((p) => !slug || p.event_slug === slug)
  const t = text.toLowerCase()
  let result
  if (/album/.test(t)) {
    result = { kind: 'album', album: albumOut(S.albums[1]) }
  } else if (/who|wer |wer$|kim/.test(t)) {
    result = { kind: 'people', title: 'Am häufigsten mit dir', persons: persons.slice(0, 3) }
  } else if (/how many|wie viele|kaç|most|meist/.test(t)) {
    result = {
      kind: 'stat',
      title: 'Fotos von dir',
      value: '42',
      detail: 'in 2 Alben dieses Jahr',
      items: items.slice(0, 3),
    }
  } else if (/which|welche|hangi/.test(t)) {
    result = {
      kind: 'clarify',
      question: 'Welches Album meinst du?',
      options: ['Annas Dreißigster', 'Sommerfest im Hof'],
    }
  } else if (/nothing|nichts|hiçbir|unicorn/.test(t)) {
    result = { kind: 'empty', title: 'Dazu habe ich nichts gefunden' }
  } else {
    result = {
      kind: 'media',
      title: 'Fotos vom Abend',
      media_ids: items.slice(0, 6).map((i) => i.id),
      items: items.slice(0, 4),
      group_by: 'time',
    }
  }
  const attachments =
    result.kind === 'stat'
      ? [
          {
            name: 'fotos-pro-monat.png',
            url: `${origin}/img/chart1/attachment.png`,
            mime: 'image/png',
            width: 1200,
            height: 800,
          },
          {
            name: 'collage.jpg',
            url: `${origin}/img/collage1/attachment.jpg`,
            mime: 'image/jpeg',
            width: 1600,
            height: 1200,
          },
          { name: 'fotos-pro-monat.csv', url: `${origin}/img/chart1/data.csv`, mime: 'text/csv' },
        ]
      : []
  return {
    understood: `Verstanden: ${text}`,
    result,
    attachments,
    suggestions: [
      { label: 'Nur Videos', text: 'nur Videos davon' },
      { label: 'Nach Mitternacht', text: 'davon nach Mitternacht' },
    ],
    saveable: result.kind === 'media' || result.kind === 'stat',
  }
}

// ------------------------------------------------------------------ server
const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', origin)
  const path = url.pathname
  const method = req.method ?? 'GET'
  res.setHeader('access-control-allow-origin', req.headers.origin ?? '*')
  res.setHeader('access-control-allow-credentials', 'true')
  res.setHeader('access-control-allow-headers', 'content-type')
  res.setHeader('access-control-allow-methods', 'GET,PUT,POST,PATCH,DELETE,OPTIONS')
  res.setHeader('access-control-expose-headers', 'ETag')
  if (method === 'OPTIONS') return res.writeHead(204).end()

  if (path === '/__mock/reset' && method === 'POST') {
    seed()
    agentConfigured = true
    return res.writeHead(204).end()
  }
  if (path === '/__mock/agent' && method === 'POST') {
    agentConfigured = url.searchParams.get('configured') !== '0'
    return res.writeHead(204).end()
  }
  if (path.startsWith('/img/')) {
    res.writeHead(200, { 'content-type': 'image/jpeg', 'cache-control': 'public, max-age=60' })
    return res.end(pixel)
  }
  if (path.startsWith('/s3/') && method === 'PUT') {
    for await (const _ of req) {
      // drain
    }
    res.writeHead(200, { etag: `"${randomBytes(8).toString('hex')}"` })
    return res.end()
  }

  const api = path.startsWith('/api/v1/') ? path.slice('/api/v1'.length) : null
  if (api === null) return error(res, 404, 'not_found', 'not found')
  const seg = api.split('/').filter(Boolean)
  const cookie = cookies(req)
  const session = Boolean(cookie.yb_session)
  const guestName = cookie.yb_guest ? S.guests.get(cookie.yb_guest) : undefined
  const viewerFor = () =>
    session
      ? { role: 'owner', display_name: S.me.display_name }
      : cookie.yb_guest
        ? {
            role: 'guest',
            guest_id: cookie.yb_guest,
            ...(guestName ? { display_name: guestName } : {}),
          }
        : { role: 'anonymous' }
  const me = () =>
    session
      ? {
          authenticated: true,
          ...S.me,
          has_claimed_person: S.persons.some((p) => p.is_me),
        }
      : { authenticated: false, locale: 'de' }
  const requireSession = () => {
    if (!session) {
      error(res, 401, 'unauthorized', 'sign in')
      return false
    }
    return true
  }

  if (api === '/health') return send(res, 200, { status: 'ok', version: 'mock' })
  if (api === '/me' && method === 'GET') return send(res, 200, me())
  if (api === '/me' && method === 'PATCH') {
    if (!requireSession()) return
    const patch = await body(req)
    if (patch.clear_birthdate) S.me.birthdate = undefined
    for (const k of ['display_name', 'birthdate', 'locale', 'link_across', 'hide_from_people'])
      if (patch[k] !== undefined) S.me[k] = patch[k]
    return send(res, 200, me())
  }
  if (api === '/me/face-data' && method === 'DELETE') {
    if (!requireSession()) return
    for (const p of S.persons) {
      p.is_me = false
      p.linked = false
    }
    return res.writeHead(204).end()
  }
  if (api === '/me/people') {
    if (!requireSession()) return
    return send(res, 200, { persons: S.persons.filter((p) => p.is_me), analyzing: false })
  }
  if (api === '/me/suggestions') {
    if (!requireSession()) return
    const p = S.persons.find((x) => x.id === 'per6'.padEnd(22, '0'))
    const suggestions =
      p && !p.is_me
        ? [
            {
              person: p,
              event_title: S.events[SLUG2].title,
              event_starts_at: S.events[SLUG2].starts_at,
              confidence: 0.71,
            },
          ]
        : []
    return send(res, 200, { suggestions })
  }
  if (api === '/me/years' && method === 'GET') {
    if (!requireSession()) return
    const events = [SLUG, SLUG2].map(eventSummary)
    return send(res, 200, {
      years: [{ year: 2026, moments: events.reduce((n, e) => n + e.of_you, 0), events }],
    })
  }
  if (seg[0] === 'me' && seg[1] === 'years' && seg[2]) {
    if (!requireSession()) return
    const year = Number(seg[2])
    if (year !== 2026) return error(res, 404, 'not_found', 'no such year')
    const events = [SLUG, SLUG2].map(eventSummary)
    const ofYou = S.media.filter((m) => gridItem(m).me).map(gridItem)
    return send(res, 200, {
      year,
      moments: ofYou.length,
      events,
      best_of_you: ofYou.slice(0, 6),
      top_people: [
        {
          person_id: 'per1'.padEnd(22, '0'),
          display_name: 'Anna',
          count: 9,
          crop_url: crop('face-per1'.padEnd(22, '0')),
        },
        {
          person_id: 'per3'.padEnd(22, '0'),
          display_name: 'Mert',
          count: 4,
          crop_url: crop('face-per3'.padEnd(22, '0')),
        },
      ],
      portrait: ofYou[0],
    })
  }
  if (api === '/me/library') {
    if (!requireSession()) return
    const items = S.media.filter((m) => m.event === null).map(gridItem)
    return send(res, 200, { items, next_cursor: null, groups: [] })
  }
  if (api === '/auth/magic' && method === 'POST') return res.writeHead(204).end()
  if (api === '/auth/verify' && method === 'POST')
    return error(res, 400, 'bad_request', 'invalid token')
  if (api === '/auth/logout' && method === 'POST')
    return res.writeHead(204, { 'set-cookie': 'yb_session=; Path=/; Max-Age=0' }).end()

  if (api === '/events' && method === 'GET') {
    if (!requireSession()) return
    return send(res, 200, { items: Object.keys(S.events).map((s) => eventFor(s, viewerFor(s))) })
  }
  if (api === '/events' && method === 'POST') {
    if (!requireSession()) return
    const b = await body(req)
    const slug = `${b.title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .slice(0, 20)}-${id().slice(0, 6).toLowerCase()}`
    S.events[slug] = {
      id: id(),
      slug,
      title: b.title,
      starts_at: b.starts_at,
      ends_at: b.ends_at ?? null,
      timezone: b.timezone ?? 'Europe/Berlin',
      location: b.location ?? null,
      host: { display_name: S.me.display_name },
      guest_upload: true,
      guest_view: true,
      faces_enabled: true,
      clustered_at: null,
      created_at: now(),
    }
    return send(res, 201, eventFor(slug, viewerFor(slug)))
  }

  if (seg[0] === 'events' && seg[1]) {
    const slug = seg[1]
    if (!S.events[slug]) return error(res, 404, 'not_found', 'no such event')
    const sub = seg[2]
    const viewer = viewerFor(slug)
    if (!sub && method === 'GET') return send(res, 200, eventFor(slug, viewer))
    if (!sub && method === 'PATCH') {
      if (!requireSession()) return
      const patch = await body(req)
      Object.assign(S.events[slug], patch)
      return send(res, 200, eventFor(slug, viewer))
    }
    if (!sub && method === 'DELETE') {
      if (!requireSession()) return
      delete S.events[slug]
      S.media = S.media.filter((m) => m.event !== slug)
      return res.writeHead(204).end()
    }
    if (sub === 'qr.svg') {
      res.writeHead(200, { 'content-type': 'image/svg+xml' })
      return res.end(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#fff"/><rect x="2" y="2" width="6" height="6"/></svg>',
      )
    }
    if (sub === 'status') {
      const c = eventCounts(slug)
      return send(res, 200, {
        total: c.ready + c.processing,
        ready: c.ready,
        processing: c.processing,
        failed: 0,
        faces_done: c.faces_done,
        clustered_at: S.events[slug].clustered_at,
      })
    }
    if (sub === 'guests' && !seg[3] && method === 'POST') {
      const gid = cookie.yb_guest ?? id()
      if (!S.guests.has(gid)) S.guests.set(gid, undefined)
      return send(
        res,
        200,
        { guest_id: gid },
        { 'set-cookie': `yb_guest=${gid}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000` },
      )
    }
    if (sub === 'guests' && seg[3] === 'me' && method === 'PATCH') {
      if (!cookie.yb_guest) return error(res, 401, 'unauthorized', 'no guest')
      const { display_name } = await body(req)
      S.guests.set(cookie.yb_guest, display_name)
      return send(res, 200, { guest_id: cookie.yb_guest, display_name })
    }
    if (sub === 'media' && method === 'GET') {
      const filter = url.searchParams.get('filter') ?? 'all'
      const mine = claimedIds()
      const items = S.media
        .filter((m) => m.event === slug)
        .filter((m) => {
          if (filter === 'videos') return m.kind === 'video'
          if (filter === 'mine') return m.mine
          if (filter === 'best') return m.score != null
          if (filter === 'me') return m.person_ids.some((p) => mine.has(p))
          if (filter.startsWith('person:')) return m.person_ids.includes(filter.slice(7))
          if (filter.startsWith('album:'))
            return S.albums.find((a) => a.id === filter.slice(6))?.item_ids.includes(m.id)
          return true
        })
        .map(gridItem)
      return send(res, 200, { items, next_cursor: null, groups: groupsFor(slug) })
    }
    if (sub === 'search' && method === 'GET') {
      const q = (url.searchParams.get('q') ?? '').toLowerCase()
      const items = S.media.filter((m) => m.event === slug).map(gridItem)
      return send(res, 200, {
        items: q.includes('unicorn') ? [] : items.slice(0, 5),
        next_cursor: null,
        groups: [],
      })
    }
    if (sub === 'best') {
      const items = S.media
        .filter((m) => m.event === slug && m.score != null)
        .sort((a, b) => b.score - a.score)
        .map(gridItem)
      return send(res, 200, { items, next_cursor: null, groups: [] })
    }
    if (sub === 'albums') {
      return send(res, 200, { albums: S.albums.filter((a) => a.event_slug === slug).map(albumOut) })
    }
    if (sub === 'people') {
      const persons = S.persons.filter((p) => p.event_slug === slug && (!p.hidden || p.is_me))
      return send(res, 200, {
        persons,
        unnamed_count: persons.filter((p) => !p.named).length,
        analyzing: slug === SLUG2,
      })
    }
    if (sub === 'uploads' && method === 'POST') {
      const { files } = await body(req)
      const result = files.map((f) => {
        const media_id = id()
        S.uploads.set(media_id, {
          client_id: f.client_id,
          name: f.name,
          size: f.size,
          type: f.type,
          state: 'uploading',
          slug,
        })
        return {
          client_id: f.client_id,
          media_id,
          mode: 'single',
          url: `${origin}/s3/${media_id}`,
          headers: { 'content-type': f.type },
          expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
        }
      })
      return send(res, 200, { uploads: result })
    }
    if (sub === 'uploads' && method === 'GET') {
      const items = [...S.uploads.entries()].map(([mid, u]) => ({
        id: mid,
        kind: 'photo',
        state: u.state,
        created_at: now(),
        error: null,
      }))
      const c = eventCounts(slug)
      return send(res, 200, {
        uploaders: items.length
          ? [
              {
                display_name: guestName ?? 'Gast',
                is_you: true,
                total: items.length,
                ready: items.filter((i) => i.state === 'ready').length,
                failed: 0,
                items,
              },
            ]
          : [],
        status: {
          total: c.ready + items.length,
          ready: c.ready,
          processing: items.length,
          failed: 0,
        },
      })
    }
    if (sub === 'events') {
      res.writeHead(200, {
        'content-type': 'text/event-stream',
        'cache-control': 'no-cache, no-transform',
        'x-accel-buffering': 'no',
        connection: 'keep-alive',
      })
      res.write('retry: 5000\n\n')
      sseClients.add(res)
      const ping = setInterval(() => res.write(': ping\n\n'), 20_000)
      req.on('close', () => {
        clearInterval(ping)
        sseClients.delete(res)
      })
      return
    }
  }

  if (seg[0] === 'uploads' && seg[1]) {
    const u = S.uploads.get(seg[1])
    if (!u) return error(res, 404, 'not_found', 'no upload')
    if (seg[2] === 'complete' && method === 'POST') {
      const item = {
        id: seg[1],
        kind: 'photo',
        state: 'queued',
        captured_at: null,
        captured_src: null,
        width: 0,
        height: 0,
        duration_ms: null,
        like_count: 0,
        liked: false,
        me: false,
        mine: true,
        person_ids: [],
        score: null,
        processing: true,
      }
      u.state = 'queued'
      u.item = item
      send(res, 200, item)
      broadcast('media.queued', { id: seg[1], mine: true })
      setTimeout(() => {
        const ready = {
          ...item,
          state: 'ready',
          processing: false,
          variants: variants(seg[1]),
          captured_at: now(),
          captured_src: 'upload',
          width: 640,
          height: 480,
        }
        u.state = 'ready'
        u.item = ready
        S.media.unshift({ event: u.slug, ...ready })
        broadcast('media.ready', ready)
      }, 800)
      return
    }
    if (!seg[2] && method === 'GET') {
      return send(res, 200, {
        media_id: seg[1],
        mode: 'single',
        url: `${origin}/s3/${seg[1]}`,
        received_parts: [],
        parts: [],
        expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
      })
    }
    if (!seg[2] && method === 'DELETE') {
      S.uploads.delete(seg[1])
      return res.writeHead(204).end()
    }
  }

  if (seg[0] === 'media') {
    if (seg[1] === 'zip' && method === 'POST') {
      const { media_ids } = await body(req)
      return send(res, 200, {
        url: `${origin}/api/v1/zips/demo`,
        expires_at: now(),
        count: media_ids.length,
      })
    }
    const m = S.media.find((x) => x.id === seg[1])
    const item = m ? gridItem(m) : S.uploads.get(seg[1] ?? '')?.item
    if (!item) return error(res, 404, 'not_found', 'no media')
    if (!seg[2] && method === 'GET')
      return send(res, 200, {
        ...item,
        uploader: { display_name: 'Mert', is_you: item.mine },
        original_filename: 'IMG_0001.jpg',
        place_name: null,
        can_delete: item.mine || session,
      })
    if (!seg[2] && method === 'DELETE') {
      if (!(item.mine || session)) return error(res, 403, 'forbidden', 'not yours')
      S.media = S.media.filter((x) => x.id !== item.id)
      for (const a of S.albums) a.item_ids = a.item_ids.filter((x) => x !== item.id)
      broadcast('media.removed', { id: item.id })
      return res.writeHead(204).end()
    }
    if (seg[2] === 'like') {
      if (!m) return error(res, 404, 'not_found', 'no media')
      m.liked = method === 'PUT'
      m.like_count = Math.max(0, m.like_count + (method === 'PUT' ? 1 : -1))
      broadcast('like.changed', { media_id: m.id, like_count: m.like_count })
      return send(res, 200, { media_id: m.id, like_count: m.like_count, liked: m.liked })
    }
    if (seg[2] === 'original') {
      res.writeHead(302, { location: `${origin}/img/${item.id}/original.jpg` })
      return res.end()
    }
    if (seg[2] === 'retry') return res.writeHead(204).end()
    if (seg[2] === 'faces') {
      return send(res, 200, {
        faces: S.faces
          .filter((f) => f.media_id === item.id)
          .map((f) => ({ ...f, crop_url: crop(f.id) })),
      })
    }
    if (seg[2] === 'event' && method === 'PUT') {
      if (!requireSession()) return
      const { event_slug } = await body(req)
      if (m) m.event = event_slug ?? null
      return send(res, 200, gridItem(m))
    }
    if (seg[2] === 'describe' && method === 'POST')
      return send(res, 200, { text: 'Eine Torte mit Kerzen.' })
  }
  if (seg[0] === 'zips') {
    res.writeHead(200, { 'content-type': 'application/zip' })
    return res.end(Buffer.from(`PK\x05\x06${'\0'.repeat(18)}`, 'binary'))
  }

  // ---------------------------------------------------------------- people
  if (seg[0] === 'faces' && seg[1]) {
    if (seg[2] === 'crop.jpg') {
      res.writeHead(200, {
        'content-type': 'image/jpeg',
        'cache-control': 'private, max-age=86400',
      })
      return res.end(pixel)
    }
    if (seg[2] === 'not-person' && method === 'POST') {
      const face = S.faces.find((f) => f.id === seg[1])
      if (face) {
        const m = S.media.find((x) => x.id === face.media_id)
        if (m) m.person_ids = m.person_ids.filter((p) => p !== face.person_id)
        face.person_id = undefined
      }
      broadcast('people.updated', { event_slug: SLUG })
      return res.writeHead(204).end()
    }
  }
  if (seg[0] === 'people') {
    if (seg[1] === 'merge' && method === 'POST') {
      const { person_ids } = await body(req)
      const [keep, ...rest] = person_ids
      const survivor = S.persons.find((p) => p.id === keep)
      for (const rid of rest) {
        const gone = S.persons.find((p) => p.id === rid)
        if (gone && survivor) {
          survivor.face_count += gone.face_count
          survivor.media_count = (survivor.media_count ?? 0) + (gone.media_count ?? 0)
          survivor.is_me = survivor.is_me || gone.is_me
        }
        for (const m of S.media) m.person_ids = m.person_ids.map((p) => (p === rid ? keep : p))
        for (const f of S.faces) if (f.person_id === rid) f.person_id = keep
      }
      S.persons = S.persons.filter((p) => !rest.includes(p.id))
      broadcast('people.updated', { event_slug: survivor?.event_slug ?? SLUG })
      return send(res, 200, survivor)
    }
    const p = S.persons.find((x) => x.id === seg[1])
    if (!p) return error(res, 404, 'not_found', 'no person')
    if (!seg[2] && method === 'GET') return send(res, 200, p)
    if (!seg[2] && method === 'PATCH') {
      const patch = await body(req)
      if (patch.display_name !== undefined) {
        p.display_name = patch.display_name
        p.named = Boolean(patch.display_name)
      }
      if (patch.hidden !== undefined) p.hidden = patch.hidden
      return send(res, 200, p)
    }
    if (seg[2] === 'claim' && method === 'POST') {
      p.is_me = true
      p.linked = true
      p.suggested_me = false
      broadcast('people.updated', { event_slug: p.event_slug })
      return send(res, 200, p)
    }
    if (seg[2] === 'claim' && method === 'DELETE') {
      p.is_me = false
      p.linked = false
      broadcast('people.updated', { event_slug: p.event_slug })
      return send(res, 200, p)
    }
    if (seg[2] === 'split' && method === 'POST') {
      const { face_ids } = await body(req)
      const fresh = {
        ...p,
        id: id(),
        display_name: null,
        named: false,
        is_me: false,
        linked: false,
        suggested_me: false,
        face_count: face_ids.length,
        media_count: face_ids.length,
      }
      p.face_count = Math.max(0, p.face_count - face_ids.length)
      for (const f of S.faces) if (face_ids.includes(f.id)) f.person_id = fresh.id
      S.persons.push(fresh)
      broadcast('people.updated', { event_slug: p.event_slug })
      return send(res, 200, fresh)
    }
  }

  // ---------------------------------------------------------------- search and agent
  if (api === '/search' && method === 'GET') {
    if (!requireSession()) return
    const q = (url.searchParams.get('q') ?? '').toLowerCase()
    const items = S.media.filter((m) => m.event !== undefined).map(gridItem)
    return send(res, 200, {
      items: q.includes('unicorn') ? [] : items.slice(0, 6),
      next_cursor: null,
      groups: [],
    })
  }
  if (api === '/agent/messages' && method === 'POST') {
    if (!agentConfigured) return error(res, 503, 'internal', 'agent_not_configured')
    const b = await body(req)
    const conversation_id = b.conversation_id ?? id()
    const turn_id = id()
    const answer = agentAnswer(b.text, b.event_slug ?? null)
    S.conversations.set(turn_id, { text: b.text, event_slug: b.event_slug ?? null })
    return send(res, 200, { conversation_id, turn_id, ...answer })
  }
  if (api === '/agent/commands' && method === 'GET') {
    const slug = url.searchParams.get('event_slug')
    return send(res, 200, {
      commands: S.commands.filter((c) =>
        slug ? c.event_slug === slug || c.scope === 'global' : true,
      ),
    })
  }
  if (api === '/agent/commands' && method === 'POST') {
    const { turn_id, label } = await body(req)
    const turn = S.conversations.get(turn_id)
    const cmd = {
      id: id(),
      name: label.toLowerCase().replace(/[^a-z0-9]+/g, '_'),
      label,
      description: turn?.text ?? label,
      scope: turn?.event_slug ? 'event' : 'global',
      event_slug: turn?.event_slug ?? undefined,
      params: {},
      shared: false,
      kind: 'search',
      created_by_agent: false,
      run_count: 0,
    }
    S.commands.push(cmd)
    return send(res, 201, cmd)
  }
  if (seg[0] === 'agent' && seg[1] === 'commands' && seg[2]) {
    const cmd = S.commands.find((c) => c.id === seg[2])
    if (!cmd) return error(res, 404, 'not_found', 'no command')
    if (!seg[3] && method === 'DELETE') {
      S.commands = S.commands.filter((c) => c.id !== cmd.id)
      return res.writeHead(204).end()
    }
    if (seg[3] === 'run' && method === 'POST') {
      const b = await body(req)
      cmd.run_count = (cmd.run_count ?? 0) + 1
      const answer = agentAnswer(cmd.description, b.event_slug ?? cmd.event_slug ?? null)
      return send(res, 200, {
        conversation_id: id(),
        turn_id: id(),
        ...answer,
        understood: cmd.label,
        saveable: false,
      })
    }
  }

  // ---------------------------------------------------------------- albums and shares
  if (api === '/albums' && method === 'POST') {
    const b = await body(req)
    const album = {
      id: id(),
      event_slug: b.event_slug,
      title: b.title,
      kind: 'manual',
      item_ids: b.media_ids ?? [],
      can_edit: true,
      allow_download: true,
    }
    S.albums.push(album)
    return send(res, 201, albumOut(album))
  }
  if (seg[0] === 'albums' && seg[1]) {
    const a = S.albums.find((x) => x.id === seg[1])
    if (!a) return error(res, 404, 'not_found', 'no album')
    if (!seg[2] && method === 'GET') return send(res, 200, albumDetail(a))
    if (!seg[2] && method === 'PATCH') {
      const b = await body(req)
      if (b.title) a.title = b.title
      if (b.add) for (const mid of b.add) if (!a.item_ids.includes(mid)) a.item_ids.push(mid)
      if (b.remove) a.item_ids = a.item_ids.filter((mid) => !b.remove.includes(mid))
      return send(res, 200, albumDetail(a))
    }
    if (!seg[2] && method === 'DELETE') {
      S.albums = S.albums.filter((x) => x.id !== a.id)
      return res.writeHead(204).end()
    }
    if (seg[2] === 'share' && method === 'POST') {
      const b = await body(req)
      const share_id = id()
      const allow_download = b.allow_download ?? true
      S.shares.set(share_id, { album_id: a.id, allow_download })
      return send(res, 201, {
        share_id,
        url: `http://localhost:3000/s/${share_id}`,
        expires_at: null,
        allow_download,
      })
    }
  }
  if (seg[0] === 's' && seg[1]) {
    const share = S.shares.get(seg[1])
    const a = share && S.albums.find((x) => x.id === share.album_id)
    if (!a) return error(res, 404, 'not_found', 'no share')
    return send(res, 200, { ...albumDetail(a, share.allow_download), can_edit: false })
  }

  // ---------------------------------------------------------------- import
  if (api === '/imports' && method === 'GET') {
    if (!requireSession()) return
    return send(res, 200, { imports: [...S.imports].reverse() })
  }
  if (api === '/imports' && method === 'POST') {
    if (!requireSession()) return
    const b = await body(req)
    const imp = {
      id: id(),
      kind: b.kind,
      state: 'uploading',
      event_slug: b.event_slug,
      stats: { found: 0, imported: 0, duplicates: 0, failed: 0, matched: 0, people_seeded: 0 },
      error: null,
      created_at: now(),
      finished_at: null,
    }
    S.imports.push(imp)
    return send(res, 201, {
      ...imp,
      upload: {
        client_id: 'archive',
        media_id: imp.id,
        mode: 'single',
        url: `${origin}/s3/${imp.id}`,
        headers: { 'content-type': 'application/zip' },
        expires_at: new Date(Date.now() + 3_600_000).toISOString(),
      },
    })
  }
  if (seg[0] === 'imports' && seg[1]) {
    if (!requireSession()) return
    const imp = S.imports.find((x) => x.id === seg[1])
    if (!imp) return error(res, 404, 'not_found', 'no import')
    if (!seg[2] && method === 'GET') return send(res, 200, imp)
    if (!seg[2] && method === 'DELETE') {
      imp.state = 'cancelled'
      return res.writeHead(204).end()
    }
    if (seg[2] === 'complete' && method === 'POST') {
      imp.state = 'queued'
      setTimeout(() => {
        imp.state = 'running'
        imp.stats = {
          found: 48,
          imported: 20,
          duplicates: 3,
          failed: 0,
          matched: 12,
          people_seeded: 1,
        }
      }, 500)
      setTimeout(() => {
        imp.state = 'done'
        imp.stats = {
          found: 48,
          imported: 41,
          duplicates: 6,
          failed: 1,
          matched: 27,
          people_seeded: 2,
        }
        imp.finished_at = now()
      }, 1500)
      return send(res, 200, imp)
    }
  }

  return error(res, 404, 'not_found', `no route for ${method} ${api}`)
})

server.listen(port, () => {
  console.log(
    `mock api on ${origin} (events /e/${SLUG}, /e/${SLUG2}; cookie yb_session=mock signs in)`,
  )
})
