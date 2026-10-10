import { expect, test } from '@playwright/test'
import { resetMock, SLUG } from './helpers'

test.describe('Turkish', () => {
  test.beforeEach(async ({ request }) => resetMock(request))

  test('a tr browser gets the landing in Turkish with tr-TR dates', async ({ request }) => {
    const res = await request.get(`/e/${SLUG}`, {
      headers: { 'accept-language': 'tr-TR,tr;q=0.9,en;q=0.8' },
    })
    expect(res.ok()).toBeTruthy()
    const html = await res.text()
    expect(html).toContain('<html lang="tr"')
    expect(html).toContain('Mert seni davet ediyor')
    expect(html).toContain('Fotoğraflarını ekle')
    expect(html).toContain('Haziran')
    expect(html).not.toMatch(/\p{Extended_Pictographic}/u)
  })

  test('the settings page switches between three languages', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await expect(page.locator('[data-lang]')).toHaveCount(3)
    await page.locator('[data-lang="tr"]').click()
    await expect(page.locator('html')).toHaveAttribute('lang', 'tr')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Ayarlar')
    await expect(page.locator('[data-lang="tr"]')).toHaveAttribute('aria-pressed', 'true')
    await page.locator('[data-lang="en"]').click()
    await expect(page.locator('html')).toHaveAttribute('lang', 'en')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Settings')
  })
})
