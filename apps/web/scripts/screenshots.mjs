// Dev helper: screenshots of the key screens at phone size against a running stack.
// usage: node scripts/screenshots.mjs <event-slug> [outDir] [baseUrl]

import { mkdirSync } from 'node:fs'
import { chromium, devices } from '@playwright/test'

const [slug, outDir = 'test-results/screens', base = 'http://localhost:3000'] =
  process.argv.slice(2)
if (!slug) throw new Error('slug required')
mkdirSync(outDir, { recursive: true })
const browser = await chromium.launch()
const ctx = await browser.newContext({ ...devices['iPhone 14'], locale: 'de-DE' })
const page = await ctx.newPage()
const errors = []
page.on('pageerror', (e) => errors.push(String(e)))
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(m.text())
})
const shot = async (path, name, after) => {
  await page.goto(`${base}${path}`, { waitUntil: 'networkidle' })
  if (after) await after()
  await page.waitForTimeout(400)
  await page.screenshot({ path: `${outDir}/${name}.png`, fullPage: false })
  console.log('shot', name, page.url())
}
await shot(`/e/${slug}`, '1-landing')
await shot(`/e/${slug}/photos`, '2-photos')
await shot(`/e/${slug}/photos`, '3-lightbox', async () => {
  const cell = page.locator('[data-cell] a, a[data-cell], [data-cell]').first()
  await cell.click()
  await page.waitForTimeout(600)
})
await shot(`/e/${slug}/upload`, '4-upload')
await shot(`/login`, '5-login')
await shot(`/e/${slug}/photos?filter=videos`, '6-videos')
console.log('page errors:', errors.length ? errors : 'none')
await browser.close()
