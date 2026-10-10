import { expect, test } from '@playwright/test'
import { resetMock, SLUG, signIn } from './helpers'

test.describe('delete', () => {
  test.beforeEach(async ({ request, context }) => {
    await resetMock(request)
    await signIn(context)
  })

  test('deletes one photo from the lightbox after confirming', async ({ page }) => {
    await page.goto(`/e/${SLUG}/photos`)
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    const cells = page.locator('[data-cell]')
    await expect(cells).toHaveCount(8)
    const firstId = await cells.first().getAttribute('data-cell')
    await cells.first().click()
    const lightbox = page.locator('[data-lightbox]')
    await expect(lightbox).toBeVisible()
    await lightbox.locator('[data-delete]').click()
    const confirm = page.locator('dialog[open] [data-confirm]')
    await expect(confirm).toBeVisible()
    await confirm.click()
    await expect(page.getByRole('status').filter({ hasText: 'Foto gelöscht' })).toBeVisible()
    await expect(page.locator('[data-lightbox]')).toHaveCount(0)
    await expect(page).toHaveURL(new RegExp(`/e/${SLUG}/photos$`))
    await expect(cells).toHaveCount(7)
    await expect(page.locator(`[data-cell="${firstId}"]`)).toHaveCount(0)
  })

  test('hosts delete a selection with "Delete N"', async ({ page }) => {
    await page.goto(`/e/${SLUG}/photos`)
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await page.getByRole('button', { name: 'Auswählen' }).click()
    const cells = page.locator('[data-cell]')
    await cells.nth(0).click()
    await cells.nth(1).click()
    const del = page.locator('[data-delete-selected]')
    await expect(del).toHaveText('2 löschen')
    await del.click()
    await expect(page.getByText('2 Fotos löschen?')).toBeVisible()
    await page.locator('dialog[open] [data-confirm]').click()
    await expect(page.getByRole('status').filter({ hasText: '2 Fotos gelöscht' })).toBeVisible()
    await expect(cells).toHaveCount(6)
  })
})
