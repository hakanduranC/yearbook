import { expect, test } from '@playwright/test'
import { resetMock, SLUG, signIn } from './helpers'

test.describe('import and library', () => {
  test.beforeEach(async ({ request, context }) => {
    await resetMock(request)
    await signIn(context)
  })

  test('uploads an archive and follows the progress card to done', async ({ page }) => {
    await page.goto('/import')
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await expect(page.getByText('takeout.google.com')).toBeVisible()
    await expect(page.locator('[data-past-import]')).toHaveCount(1)
    await page.locator('[data-kind="zip"]').click()
    await expect(page.locator('[data-kind="zip"]')).toHaveAttribute('aria-checked', 'true')
    await expect(page.locator('[data-start-import]')).toBeDisabled()
    await page.getByTestId('import-file').setInputFiles({
      name: 'urlaub.zip',
      mimeType: 'application/zip',
      buffer: Buffer.from(`PK\x05\x06${'\0'.repeat(18)}`, 'binary'),
    })
    await expect(page.locator('[data-file-name]')).toContainText('urlaub.zip')
    await page.locator('[data-start-import]').click()
    const card = page.locator('[data-import-card]')
    await expect(card).toBeVisible()
    await expect(card).toHaveAttribute('data-state', 'done', { timeout: 15_000 })
    await expect(card.locator('[data-stat="importiert"]')).toHaveText('41')
    await expect(card.locator('[data-stat="Duplikate"]')).toHaveText('6')
    await expect(card.locator('[data-stat="Alben zugeordnet"]')).toHaveText('27')
    await expect(card.locator('[data-stat="Namen übernommen"]')).toHaveText('2')
    await expect(card.getByText('Zip-Datei eines Ordners · fertig')).toBeVisible()
  })

  test('the library moves unassigned items into an event', async ({ page }) => {
    await page.goto('/library')
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    const tiles = page.locator('[data-tile]')
    await expect(tiles).toHaveCount(3)
    await page.locator('[data-select]').click()
    await tiles.nth(0).click()
    await tiles.nth(1).click()
    await expect(page.locator('[data-move]')).toHaveText('2 verschieben')
    await page.locator('[data-move]').click()
    await page.locator(`[data-pick-slug="${SLUG}"]`).click()
    await expect(page.getByRole('status').filter({ hasText: '2 verschoben' })).toBeVisible()
    await expect(tiles).toHaveCount(1)
    await page.goto(`/e/${SLUG}/photos`)
    await expect(page.locator('[data-cell]')).toHaveCount(10)
  })
})
