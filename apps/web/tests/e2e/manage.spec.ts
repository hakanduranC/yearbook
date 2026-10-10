import { expect, test } from '@playwright/test'
import { mockId, resetMock, SLUG, SLUG2, signIn } from './helpers'

test.describe('owner dashboard, albums and highlights', () => {
  test.beforeEach(async ({ request, context }) => {
    await resetMock(request)
    await signIn(context)
  })

  test('lists hosted events with quick actions and deletes one after confirming', async ({
    page,
  }) => {
    await page.goto('/manage')
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    const events = page.locator('[data-manage-event]')
    await expect(events).toHaveCount(2)
    const party = page.locator(`[data-manage-event="${SLUG}"]`)
    await expect(party.getByText('alles verarbeitet')).toBeVisible()
    await expect(party.getByRole('link', { name: 'Teilen (QR)' })).toHaveAttribute(
      'href',
      `/e/${SLUG}/share`,
    )
    await expect(party.getByRole('link', { name: 'Personen verwalten' })).toHaveAttribute(
      'href',
      `/e/${SLUG}/people/manage`,
    )
    await expect(party.locator('[data-album]')).toHaveCount(2)
    await expect(page.locator('[data-go-import]')).toHaveAttribute('href', '/import')

    const fest = page.locator(`[data-manage-event="${SLUG2}"]`)
    await fest.locator('[data-delete-event]').click()
    await expect(page.getByText('„Sommerfest im Hof“ löschen?')).toBeVisible()
    await page.locator('dialog[open] [data-confirm]').click()
    await expect(page.getByRole('status').filter({ hasText: 'Album gelöscht' })).toBeVisible()
    await expect(events).toHaveCount(1)
  })

  test('renames and deletes albums from the dashboard', async ({ page }) => {
    await page.goto('/manage')
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    const cake = page.locator(`[data-album="${mockId('alb-cake')}"]`)
    await cake.locator('[data-rename-album]').click()
    const field = page.locator('dialog[open]').getByLabel('Neuer Name')
    await field.fill('Torte und Kerzen')
    await page.locator('dialog[open]').getByRole('button', { name: 'Speichern' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Umbenannt' })).toBeVisible()
    await expect(cake.getByText('Torte und Kerzen')).toBeVisible()
    await cake.locator('[data-delete-album]').click()
    await page.locator('dialog[open] [data-confirm]').click()
    await expect(page.locator(`[data-manage-event="${SLUG}"] [data-album]`)).toHaveCount(1)
  })

  test('album detail removes items in select mode and shares a link', async ({ page }) => {
    await page.goto(`/albums/${mockId('alb-high')}`)
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Highlights')
    const tiles = page.locator('[data-tile]')
    await expect(tiles).toHaveCount(3)
    await page.locator('[data-select]').click()
    await tiles.first().click()
    await expect(page.locator('[data-remove-selected]')).toHaveText('1 entfernen')
    await page.locator('[data-remove-selected]').click()
    await page.locator('dialog[open] [data-confirm]').click()
    await expect(page.getByRole('status').filter({ hasText: '1 entfernt' })).toBeVisible()
    await expect(tiles).toHaveCount(2)

    await page.locator('[data-share-album]').click()
    await page.locator('[data-create-link]').click()
    const url = page.locator('[data-share-url]')
    await expect(url).toContainText('/s/')
    const href = (await url.textContent()) ?? ''
    await page.goto(new URL(href).pathname)
    await expect(page.locator('[data-shared-album]')).toBeVisible()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Highlights')
    await expect(page.locator('[data-tile]')).toHaveCount(2)
    await expect(page.locator('[data-download-all]')).toBeVisible()
  })

  test('the shared album renders OG tags on the server and honors allow_download', async ({
    request,
  }) => {
    const res = await request.get(`/s/${mockId('share2')}`)
    expect(res.ok()).toBeTruthy()
    const html = await res.text()
    expect(html).toMatch(/<meta property="og:title" content="Die Torte"/)
    expect(html).toMatch(
      /<meta property="og:image" content="http:\/\/localhost:8089\/img\/p5\/large\.webp"/,
    )
    expect(html).toContain('Download ist für diesen Link deaktiviert.')
    expect(html).not.toContain('data-download-all')
    const missing = await request.get(`/s/${mockId('nope')}`)
    expect(await missing.text()).toContain('Diesen Link gibt es nicht mehr.')
  })

  test('highlights pin into the album and open the share sheet', async ({ page }) => {
    await page.goto(`/e/${SLUG}/best`)
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await expect(page.locator('[data-tile]')).toHaveCount(8)
    await expect(page.getByText('3 im Album')).toBeVisible()
    const pin = page.locator(`[data-pin="${mockId('p5')}"]`)
    await expect(pin).toHaveAttribute('aria-pressed', 'false')
    await pin.click()
    await expect(page.getByRole('status').filter({ hasText: 'Angeheftet' })).toBeVisible()
    await expect(pin).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByText('4 im Album')).toBeVisible()
    await page.locator(`[data-pin="${mockId('p1')}"]`).click()
    await expect(page.getByText('3 im Album')).toBeVisible()
    await page.locator('[data-share-highlights]').click()
    await expect(page.getByRole('switch')).toBeVisible()
    await page.locator('[data-create-link]').click()
    await expect(page.locator('[data-share-url]')).toContainText('/s/')
  })
})
