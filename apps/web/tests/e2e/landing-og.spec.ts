import { expect, test } from '@playwright/test'

const slug = 'demo-party-abc123'

test.describe('event landing SSR', () => {
  test('renders OG tags from the cover large variant', async ({ request }) => {
    const res = await request.get(`/e/${slug}`, { headers: { 'accept-language': 'de' } })
    expect(res.ok()).toBeTruthy()
    const html = await res.text()
    expect(html).toContain('<html lang="de"')
    expect(html).toMatch(/<meta property="og:title" content="Annas Dreißigster"/)
    expect(html).toMatch(
      /<meta property="og:image" content="http:\/\/localhost:8089\/img\/cover\/large\.webp"/,
    )
    expect(html).toMatch(
      /<meta property="og:url" content="http:\/\/localhost:3000\/e\/demo-party-abc123"/,
    )
    expect(html).toContain('Mert lädt dich ein zu')
    expect(html).toContain('Deine Fotos hinzufügen')
  })

  test('falls back to English from Accept-Language', async ({ request }) => {
    const res = await request.get(`/e/${slug}`, {
      headers: { 'accept-language': 'en-US,en;q=0.9' },
    })
    const html = await res.text()
    expect(html).toContain('<html lang="en"')
    expect(html).toContain('Mert invites you to')
    expect(html).toContain('Add your photos')
  })

  test('the yb_lang cookie wins over Accept-Language', async ({ request }) => {
    const res = await request.get(`/e/${slug}`, {
      headers: { 'accept-language': 'de', cookie: 'yb_lang=en' },
    })
    expect(await res.text()).toContain('<html lang="en"')
  })

  test('unknown events render the not found state', async ({ request }) => {
    const res = await request.get('/e/does-not-exist')
    expect(res.status()).toBe(404)
  })
})
