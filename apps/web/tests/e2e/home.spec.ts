import { expect, test } from '@playwright/test'
import { claimOnMock, resetMock, SLUG, SLUG2, signIn } from './helpers'

test.describe('home and year', () => {
  test.beforeEach(async ({ request, context }) => {
    await resetMock(request)
    await signIn(context)
  })

  test('anonymous visitors keep the intro', async ({ page, context }) => {
    await context.clearCookies()
    await page.goto('/')
    await expect(page.locator('[data-home-anonymous]')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Anmelden' })).toBeVisible()
  })

  test('greets with moments, fans the photos of you and swipes', async ({ page, request }) => {
    await claimOnMock(request, 'per2')
    await page.goto('/')
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Hallo, Hakan')
    await expect(page.locator('[data-moments]')).toHaveText('in 4 Momenten dieses Jahr')

    const party = page.locator(`[data-home-event="${SLUG}"]`)
    await expect(party.getByText('4 von dir')).toBeVisible()
    await expect(party.getByText('Annas Dreißigster')).toBeVisible()
    const fan = party.locator('[data-fan]')
    await expect(fan).toBeVisible()
    await expect(fan.locator('[data-fan-card]')).toHaveCount(4)
    await expect(fan).toHaveAttribute('data-active', '0')
    await expect(party.getByRole('tab')).toHaveCount(4)

    // drag left past a quarter of the width
    await fan.scrollIntoViewIfNeeded()
    const box = await fan.boundingBox()
    if (!box) throw new Error('no fan')
    const y = box.y + box.height / 2
    await page.mouse.move(box.x + box.width * 0.7, y)
    await page.mouse.down()
    for (let i = 1; i <= 8; i++) {
      await page.mouse.move(box.x + box.width * 0.7 - (box.width * 0.5 * i) / 8, y)
    }
    await page.mouse.up()
    await expect(fan).toHaveAttribute('data-active', '1')

    // keyboard
    await fan.focus()
    await page.keyboard.press('ArrowRight')
    await expect(fan).toHaveAttribute('data-active', '2')
    await page.keyboard.press('ArrowLeft')
    await expect(fan).toHaveAttribute('data-active', '1')
    await party.getByRole('tab').nth(3).click()
    await expect(fan).toHaveAttribute('data-active', '3')

    // the other event has no photos of the viewer: cover plus "still analyzing"
    const fest = page.locator(`[data-home-event="${SLUG2}"]`)
    await expect(fest.locator('[data-fan]')).toHaveCount(0)
    await expect(fest.getByText('wird noch ausgewertet')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Personen' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Neues Album' })).toBeVisible()
  })

  test('cross-event suggestions can be dismissed for the session or confirmed', async ({
    page,
  }) => {
    await page.goto('/')
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    const card = page.locator('[data-suggestion]')
    await expect(card).toBeVisible()
    await expect(card.getByText('Auch du, bei Sommerfest im Hof?')).toBeVisible()
    await card.locator('[data-dismiss-suggestion]').click()
    await expect(card).toHaveCount(0)
    await page.reload()
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await expect(page.locator('[data-suggestion]')).toHaveCount(0)

    // a fresh session sees it again and confirms
    await page.evaluate(() => sessionStorage.clear())
    await page.goto('/people')
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    const again = page.locator('[data-suggestion]')
    await expect(again).toBeVisible()
    await again.locator('[data-confirm-suggestion]').click()
    await expect(page.getByRole('status').filter({ hasText: 'Verknüpft' })).toBeVisible()
    await expect(page.locator('[data-suggestion]')).toHaveCount(0)
    await expect(page.locator('[data-person]')).toHaveCount(1)
    await page.goto('/')
    await expect(page.locator(`[data-home-event="${SLUG2}"]`).getByText('2 von dir')).toBeVisible()
  })

  test('your year shows the recap line, best shots and top people', async ({ page, request }) => {
    await claimOnMock(request, 'per2')
    await page.goto('/year/2026')
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await expect(page.locator('[data-year-summary]')).toHaveText(
      'In 4 Momenten · 2 Alben · am häufigsten mit Anna',
    )
    await expect(page.getByText('Deine besten Aufnahmen')).toBeVisible()
    await expect(page.locator('[data-tile]')).toHaveCount(4)
    await expect(page.getByText('Anna', { exact: true })).toBeVisible()
    await expect(page.getByText('9 Fotos')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Mein Jahr teilen' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Alle speichern' })).toBeEnabled()
  })
})
