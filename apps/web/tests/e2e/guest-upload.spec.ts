import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, type Page, type Route, test } from '@playwright/test'
import { FIXTURE_COUNT, fixturesDir } from './global-setup'

const slug = 'demo-party-abc123'
const STORAGE = 'https://storage.test'
const IMG = 'http://localhost:8089/img'

const fixtures = Array.from({ length: FIXTURE_COUNT }, (_, i) =>
  join(fixturesDir, `photo-${String(i + 1).padStart(2, '0')}.jpg`),
)

const variants = (key: string) => ({
  thumb: `${IMG}/${key}/thumb.webp`,
  small: `${IMG}/${key}/small.webp`,
  medium: `${IMG}/${key}/medium.webp`,
  large: `${IMG}/${key}/large.webp`,
})

/** In-memory API behind page.route so the browser flow is deterministic. SSR still talks to the mock server. */
function installMocks(page: Page) {
  const uploads = new Map<
    string,
    { client_id: string; size: number; state: string; put: boolean; item?: Record<string, unknown> }
  >()
  const ready: Record<string, unknown>[] = []
  let guest: string | null = null
  let guestName: string | null = null
  let counter = 0
  const newId = () => `mock${String(++counter).padStart(18, '0')}`

  const event = () => ({
    id: 'evt000000000000000000',
    slug,
    title: 'Annas Dreißigster',
    starts_at: '2026-06-14T18:00:00Z',
    ends_at: null,
    timezone: 'Europe/Berlin',
    location: 'Kantine Fabrik',
    cover: variants('cover'),
    host: { display_name: 'Mert' },
    guest_upload: true,
    guest_view: true,
    counts: { photos: ready.length, videos: 0, ready: ready.length, processing: 0, failed: 0 },
    viewer: guest
      ? { role: 'guest', guest_id: guest, ...(guestName ? { display_name: guestName } : {}) }
      : { role: 'anonymous' },
    created_at: '2026-06-01T00:00:00Z',
  })

  const json = (route: Route, body: unknown, status = 200, headers: Record<string, string> = {}) =>
    route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body), headers })

  const putCalls: string[] = []

  page.route(`${STORAGE}/**`, async (route) => {
    putCalls.push(route.request().url())
    const id = route.request().url().split('/').pop() ?? ''
    const u = uploads.get(id)
    if (u) u.put = true
    await route.fulfill({
      status: 200,
      headers: { etag: `"etag-${id}"`, 'access-control-expose-headers': 'ETag' },
    })
  })

  page.route('**/api/v1/**', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname.replace(/^\/api\/v1/, '')
    const method = req.method()

    if (path === `/events/${slug}/events`) return route.continue()
    if (path === `/events/${slug}` && method === 'GET') return json(route, event())
    if (path === '/me') return json(route, { authenticated: false, locale: 'de' })
    if (path === `/events/${slug}/guests` && method === 'POST') {
      guest = guest ?? 'guest0000000000000000a'
      return json(route, { guest_id: guest }, 200, {
        'set-cookie': `yb_guest=${guest}; Path=/; SameSite=Lax`,
      })
    }
    if (path === `/events/${slug}/guests/me` && method === 'PATCH') {
      guestName = (req.postDataJSON() as { display_name: string }).display_name
      return json(route, { guest_id: guest, display_name: guestName })
    }
    if (path === `/events/${slug}/media` && method === 'GET') {
      const filter = url.searchParams.get('filter') ?? 'all'
      const items =
        filter === 'mine' ? ready.filter((i) => i.mine) : filter === 'videos' ? [] : ready
      return json(route, { items, next_cursor: null, groups: [] })
    }
    if (path === `/events/${slug}/uploads` && method === 'POST') {
      const { files } = req.postDataJSON() as {
        files: Array<{ client_id: string; size: number; type: string }>
      }
      expect(files.length).toBeLessThanOrEqual(20)
      const result = files.map((f) => {
        const media_id = newId()
        uploads.set(media_id, {
          client_id: f.client_id,
          size: f.size,
          state: 'uploading',
          put: false,
        })
        return {
          client_id: f.client_id,
          media_id,
          mode: 'single',
          url: `${STORAGE}/put/${media_id}`,
          headers: { 'content-type': f.type },
          expires_at: new Date(Date.now() + 900_000).toISOString(),
        }
      })
      return json(route, { uploads: result })
    }
    const complete = path.match(/^\/uploads\/([^/]+)\/complete$/)
    if (complete && method === 'POST') {
      const id = complete[1] ?? ''
      const u = uploads.get(id)
      if (!u) return json(route, { error: { code: 'not_found', message: 'no upload' } }, 404)
      if (!u.put)
        return json(route, { error: { code: 'conflict', message: 'object missing' } }, 409)
      u.state = 'ready'
      const item = {
        id,
        kind: 'photo',
        state: 'ready',
        captured_at: new Date().toISOString(),
        captured_src: 'upload',
        width: 640,
        height: 480,
        duration_ms: null,
        variants: variants(id),
        like_count: 0,
        liked: false,
        me: false,
        mine: true,
        person_ids: [],
        score: null,
        processing: false,
      }
      u.item = item
      ready.unshift(item)
      return json(route, item)
    }
    const status = path.match(/^\/uploads\/([^/]+)$/)
    if (status && method === 'GET') {
      return json(route, {
        media_id: status[1],
        mode: 'single',
        url: `${STORAGE}/put/${status[1]}`,
        received_parts: [],
        parts: [],
        expires_at: new Date(Date.now() + 900_000).toISOString(),
      })
    }
    const detail = path.match(/^\/media\/([^/]+)$/)
    if (detail && method === 'GET') {
      const item = ready.find((i) => i.id === detail[1])
      if (!item) return json(route, { error: { code: 'not_found', message: 'no media' } }, 404)
      return json(route, {
        ...item,
        uploader: { display_name: guestName ?? 'Gast', is_you: true },
        can_delete: true,
      })
    }
    return json(route, { error: { code: 'not_found', message: `unmocked ${method} ${path}` } }, 404)
  })

  return { uploads, ready, putCalls, guestName: () => guestName }
}

test.describe('guest upload', () => {
  test('uploads 20 photos, asks for a name, and shows the new cells in the grid', async ({
    page,
  }) => {
    const mocks = installMocks(page)

    await page.goto(`/e/${slug}`)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Annas Dreißigster')
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await page.getByRole('link', { name: 'Deine Fotos hinzufügen' }).click()
    await expect(page).toHaveURL(new RegExp(`/e/${slug}/upload$`))
    await expect(page.locator('[data-name-sheet]')).toBeHidden()

    await page.getByTestId('file-input').setInputFiles(fixtures)

    const rows = page.locator('[data-upload-item]')
    await expect(rows).toHaveCount(FIXTURE_COUNT)
    await expect(rows.locator('[data-status="done"]')).toHaveCount(0)
    await expect(page.locator('[data-upload-item][data-status="done"]')).toHaveCount(
      FIXTURE_COUNT,
      { timeout: 30_000 },
    )
    await expect(page.locator('[data-upload-summary]')).toContainText(
      `${FIXTURE_COUNT} von ${FIXTURE_COUNT}`,
    )
    expect(mocks.putCalls).toHaveLength(FIXTURE_COUNT)
    expect([...mocks.uploads.values()].every((u) => u.state === 'ready')).toBe(true)

    const sheet = page.locator('[data-name-sheet]')
    await expect(sheet).toBeVisible()
    await expect(page.locator('dialog[open]')).toHaveCount(1)
    await expect(page.getByText('Fertig. Willst du Fotos von dir finden?')).toBeVisible()
    await sheet.getByLabel('Dein Name').fill('Lea')
    await sheet.getByRole('button', { name: 'Weiter' }).click()
    expect(mocks.guestName()).toBe('Lea')

    await expect(page).toHaveURL(new RegExp(`/e/${slug}/photos`))
    const cells = page.locator('[data-cell]')
    await expect(cells).toHaveCount(FIXTURE_COUNT)
    for (const id of mocks.ready.slice(0, 3).map((i) => i.id as string)) {
      await expect(page.locator(`[data-cell="${id}"]`)).toBeVisible()
    }
    await expect(page.locator('[data-group="new"], [data-group="other"]').first()).toBeVisible()
  })

  test('fixture JPEGs decode', async () => {
    const first = readFileSync(fixtures[0] ?? '')
    expect(first[0]).toBe(0xff)
    expect(first[1]).toBe(0xd8)
  })
})
