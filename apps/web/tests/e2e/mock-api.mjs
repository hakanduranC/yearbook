// Minimal in-memory stand-in for the Go API, used by Playwright and for local SSR checks.
// Usage: node tests/e2e/mock-api.mjs [port]

import { randomBytes } from 'node:crypto'
import { createServer } from 'node:http'

const port = Number(process.argv[2] ?? process.env.MOCK_API_PORT ?? 8089)
const origin = `http://localhost:${port}`
const id = () => randomBytes(16).toString('base64url')
const now = () => new Date().toISOString()

const SLUG = 'demo-party-abc123'
const variants = (key) => ({
  thumb: `${origin}/img/${key}/thumb.webp`,
  small: `${origin}/img/${key}/small.webp`,
  medium: `${origin}/img/${key}/medium.webp`,
  large: `${origin}/img/${key}/large.webp`,
})

const event = {
  id: id(),
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
  counts: { photos: 6, videos: 1, ready: 7, processing: 0, failed: 0 },
  viewer: { role: 'anonymous' },
  created_at: now(),
}

const base = (i, captured_at, extra = {}) => ({
  id: id(),
  kind: 'photo',
  state: 'ready',
  captured_at,
  captured_src: 'exif',
  width: 4032,
  height: 3024,
  duration_ms: null,
  variants: variants(`p${i}`),
  like_count: i % 3,
  liked: false,
  me: i === 2,
  mine: false,
  person_ids: [],
  score: null,
  processing: false,
  ...extra,
})

const media = [
  base(1, '2026-06-14T21:40:00Z'),
  base(2, '2026-06-14T21:10:00Z'),
  base(3, '2026-06-14T20:05:00Z', {
    kind: 'video',
    duration_ms: 65_000,
    poster: `${origin}/img/p3/poster.webp`,
    video_url: `${origin}/img/p3/video.mp4`,
  }),
  base(4, '2026-06-14T17:30:00Z'),
  base(5, '2026-06-14T17:05:00Z'),
  base(6, '2026-06-14T16:20:00Z'),
  base(7, '2026-06-14T16:02:00Z'),
]
const groups = [
  { label: 'night', start: '2026-06-14T20:00:00Z', end: '2026-06-15T03:00:00Z', count: 3 },
  { label: 'evening', start: '2026-06-14T15:00:00Z', end: '2026-06-14T20:00:00Z', count: 4 },
]

const uploads = new Map() // media_id -> {state, item}
const guests = new Map() // cookie -> display_name
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

// A 1x1 JPEG so <img> tags resolve.
const pixel = Buffer.from(
  '/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=',
  'base64',
)

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
  const guestName = cookie.yb_guest ? guests.get(cookie.yb_guest) : undefined
  const viewer = cookie.yb_guest
    ? {
        role: 'guest',
        guest_id: cookie.yb_guest,
        ...(guestName ? { display_name: guestName } : {}),
      }
    : { role: 'anonymous' }

  if (api === '/health') return send(res, 200, { status: 'ok', version: 'mock' })
  if (api === '/me') return send(res, 200, { authenticated: false, locale: 'de' })
  if (api === '/auth/magic' && method === 'POST') return res.writeHead(204).end()
  if (api === '/auth/verify' && method === 'POST')
    return error(res, 400, 'bad_request', 'invalid token')
  if (api === '/events' && method === 'GET') return error(res, 401, 'unauthorized', 'sign in')

  if (seg[0] === 'events' && seg[1]) {
    if (seg[1] !== SLUG) return error(res, 404, 'not_found', 'no such event')
    const sub = seg[2]
    if (!sub && method === 'GET') return send(res, 200, { ...event, viewer })
    if (sub === 'qr.svg') {
      res.writeHead(200, { 'content-type': 'image/svg+xml' })
      return res.end(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#fff"/><rect x="2" y="2" width="6" height="6"/></svg>',
      )
    }
    if (sub === 'status') return send(res, 200, { total: 7, ready: 7, processing: 0, failed: 0 })
    if (sub === 'guests' && !seg[3] && method === 'POST') {
      const gid = cookie.yb_guest ?? id()
      if (!guests.has(gid)) guests.set(gid, undefined)
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
      guests.set(cookie.yb_guest, display_name)
      return send(res, 200, { guest_id: cookie.yb_guest, display_name })
    }
    if (sub === 'media' && method === 'GET') {
      const filter = url.searchParams.get('filter') ?? 'all'
      const items = media.filter((m) =>
        filter === 'videos'
          ? m.kind === 'video'
          : filter === 'mine'
            ? m.mine
            : filter === 'best'
              ? m.score != null
              : true,
      )
      return send(res, 200, { items, next_cursor: null, groups })
    }
    if (sub === 'uploads' && method === 'POST') {
      const { files } = await body(req)
      const result = files.map((f) => {
        const media_id = id()
        uploads.set(media_id, {
          client_id: f.client_id,
          name: f.name,
          size: f.size,
          type: f.type,
          state: 'uploading',
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
      const items = [...uploads.entries()].map(([mid, u]) => ({
        id: mid,
        kind: 'photo',
        state: u.state,
        created_at: now(),
        error: null,
      }))
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
        status: { total: 7 + items.length, ready: 7, processing: items.length, failed: 0 },
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
    const u = uploads.get(seg[1])
    if (!u) return error(res, 404, 'not_found', 'no upload')
    if (seg[2] === 'complete' && method === 'POST') {
      const item = {
        ...base(0, null, {
          id: seg[1],
          state: 'queued',
          processing: true,
          variants: undefined,
          mine: true,
          like_count: 0,
          me: false,
          captured_src: null,
          width: 0,
          height: 0,
        }),
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
        media.unshift(ready)
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
      uploads.delete(seg[1])
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
    const item = media.find((m) => m.id === seg[1]) ?? uploads.get(seg[1] ?? '')?.item
    if (!item) return error(res, 404, 'not_found', 'no media')
    if (!seg[2] && method === 'GET')
      return send(res, 200, {
        ...item,
        uploader: { display_name: 'Mert', is_you: item.mine },
        original_filename: 'IMG_0001.jpg',
        place_name: null,
        can_delete: item.mine,
      })
    if (seg[2] === 'like') {
      item.liked = method === 'PUT'
      item.like_count = Math.max(0, item.like_count + (method === 'PUT' ? 1 : -1))
      broadcast('like.changed', { media_id: item.id, like_count: item.like_count })
      return send(res, 200, { media_id: item.id, like_count: item.like_count, liked: item.liked })
    }
    if (seg[2] === 'original') {
      res.writeHead(302, { location: `${origin}/img/${item.id}/original.jpg` })
      return res.end()
    }
    if (seg[2] === 'retry') return res.writeHead(204).end()
  }
  if (seg[0] === 'zips') {
    res.writeHead(200, { 'content-type': 'application/zip' })
    return res.end(Buffer.from(`PK\x05\x06${'\0'.repeat(18)}`, 'binary'))
  }
  return error(res, 404, 'not_found', `no route for ${method} ${api}`)
})

server.listen(port, () => {
  console.log(`mock api on ${origin} (event /e/${SLUG})`)
})
