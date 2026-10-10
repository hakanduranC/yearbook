import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

export const FIXTURE_COUNT = 20
export const fixturesDir = join(dirname(fileURLToPath(import.meta.url)), 'fixtures')

/** Renders 20 distinct JPEGs with Chromium's canvas encoder so the upload path sees real image files. */
export default async function globalSetup() {
  mkdirSync(fixturesDir, { recursive: true })
  const missing = Array.from({ length: FIXTURE_COUNT }, (_, i) => i + 1).filter(
    (n) => !existsSync(join(fixturesDir, `photo-${String(n).padStart(2, '0')}.jpg`)),
  )
  if (missing.length === 0) return
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage()
    for (const n of missing) {
      const dataUrl = await page.evaluate((index) => {
        const canvas = document.createElement('canvas')
        canvas.width = 640
        canvas.height = 480
        const ctx = canvas.getContext('2d')
        if (!ctx) throw new Error('no canvas')
        const hue = (index * 37) % 360
        const grad = ctx.createLinearGradient(0, 0, 640, 480)
        grad.addColorStop(0, `hsl(${hue} 40% 70%)`)
        grad.addColorStop(1, `hsl(${(hue + 60) % 360} 35% 45%)`)
        ctx.fillStyle = grad
        ctx.fillRect(0, 0, 640, 480)
        ctx.fillStyle = '#141414'
        ctx.font = 'bold 120px sans-serif'
        ctx.fillText(String(index), 60, 300)
        return canvas.toDataURL('image/jpeg', 0.82)
      }, n)
      const base64 = dataUrl.split(',')[1] ?? ''
      writeFileSync(
        join(fixturesDir, `photo-${String(n).padStart(2, '0')}.jpg`),
        Buffer.from(base64, 'base64'),
      )
    }
  } finally {
    await browser.close()
  }
}
