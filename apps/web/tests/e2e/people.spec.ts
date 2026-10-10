import { expect, test } from '@playwright/test'
import { mockId, resetMock, SLUG, signIn } from './helpers'

test.describe('people', () => {
  test.beforeEach(async ({ request }) => resetMock(request))

  test('shows the privacy line, the "Is this you?" card and claims the person', async ({
    page,
  }) => {
    await page.goto(`/e/${SLUG}/people`)
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await expect(page.getByText('Wir gruppieren Gesichter')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Einstellungen' })).toHaveAttribute(
      'href',
      '/settings',
    )
    const card = page.locator('[data-is-this-you]')
    await expect(card).toBeVisible()
    await expect(card.getByText('Bist du das?')).toBeVisible()
    await expect(page.locator('[data-person]')).toHaveCount(4)
    await expect(page.getByText('2 ohne Namen')).toBeVisible()

    await card.locator('[data-claim]').click()
    await expect(page.getByRole('status').filter({ hasText: 'Gespeichert' })).toBeVisible()
    await expect(card).toHaveCount(0)
    await expect(page.locator(`[data-person="${mockId('per2')}"]`)).toContainText('Du')

    await page.goto(`/e/${SLUG}/photos`)
    await expect(page.locator('[data-me-pill]')).toHaveText(/Ich · 4/)
    await expect(page.locator('[data-filter="me"]')).toBeVisible()
    await page.locator('[data-me-pill]').click()
    await expect(page).toHaveURL(/filter=me/)
    await expect(page.locator('[data-cell]')).toHaveCount(4)
  })

  test('the "Not me" answer hides the card for this visit', async ({ page }) => {
    await page.goto(`/e/${SLUG}/people`)
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await page.locator('[data-not-me]').click()
    await expect(page.locator('[data-is-this-you]')).toHaveCount(0)
  })

  test('the person page renames inline and lists their photos', async ({ page }) => {
    await page.goto(`/e/${SLUG}/people/${mockId('per1')}`)
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    const name = page.locator('[data-person-name]')
    await expect(name).toHaveValue('Anna')
    await expect(page.locator('[data-cell]')).toHaveCount(3)
    await name.fill('Anna B.')
    await name.press('Enter')
    await expect(page.getByRole('status').filter({ hasText: 'Gespeichert' })).toBeVisible()
    await page.goto(`/e/${SLUG}/people`)
    await expect(page.locator(`[data-person="${mockId('per1')}"]`)).toContainText('Anna B.')
  })

  test('the lightbox people sheet reports a wrong person', async ({ page }) => {
    await page.goto(`/e/${SLUG}/photos/${mockId('p1')}`)
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await page.locator('[data-people]').click()
    await expect(page.getByText('Wer ist auf dem Foto')).toBeVisible()
    await expect(page.locator('[data-face]')).toHaveCount(2)
    await page.locator('[data-not-person]').first().click()
    await expect(page.getByRole('status').filter({ hasText: 'Danke' }).first()).toBeVisible()
    await expect(page.locator('[data-not-person]')).toHaveCount(1)
  })

  test('hosts merge two persons and split faces off', async ({ page, context }) => {
    await signIn(context)
    await page.goto(`/e/${SLUG}/people/manage`)
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    const rows = page.locator('[data-manage-person]')
    await expect(rows).toHaveCount(4)
    const merge = page.locator('[data-merge]')
    await expect(merge).toBeDisabled()
    await page.locator(`[data-person="${mockId('per1')}"]`).click()
    await page.locator(`[data-person="${mockId('per4')}"]`).click()
    await expect(merge).toHaveText('2 zusammenführen')
    await merge.click()
    await expect(page.getByRole('status').filter({ hasText: 'Zusammengeführt' })).toBeVisible()
    await expect(rows).toHaveCount(3)

    await rows.first().locator('[data-faces-toggle]').click()
    const strip = page.locator('[data-face-strip]')
    await expect(strip).toBeVisible()
    const faces = strip.locator('[data-face]')
    await expect(faces.first()).toBeVisible()
    await faces.first().click()
    await strip.locator('[data-split]').click()
    await expect(page.getByRole('status').filter({ hasText: 'Abgetrennt' })).toBeVisible()
    await expect(rows).toHaveCount(4)
  })
})
