import { expect, type Page, test } from '@playwright/test'
import { resetMock, SLUG, setAgentConfigured, signIn } from './helpers'

async function ask(page: Page, text: string) {
  const input = page.locator('[data-ask] input')
  await input.fill(text)
  await input.press('Enter')
}

test.describe('search and agent', () => {
  test.beforeEach(async ({ request, context }) => {
    await resetMock(request)
    await signIn(context)
  })

  test('renders every result kind and keeps the conversation', async ({ page }) => {
    await page.goto(`/e/${SLUG}/search`)
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await expect(page.locator('[data-prompt]')).toHaveCount(6)

    const conversationIds: Array<string | undefined> = []
    page.on('request', (req) => {
      if (req.url().endsWith('/agent/messages') && req.method() === 'POST') {
        conversationIds.push((req.postDataJSON() as { conversation_id?: string }).conversation_id)
      }
    })

    // media: 4 items inline plus 2 ids resolved by detail fetches; the first answer is slowed
    // down so the skeleton grid is observable
    await page.route(
      '**/api/v1/agent/messages',
      async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 700))
        await route.continue()
      },
      { times: 1 },
    )
    await ask(page, 'Fotos vom Abend')
    await expect(page.locator('[data-thinking] [data-skeleton]')).toBeVisible()
    const media = page.locator('[data-result="media"]')
    await expect(media).toBeVisible()
    await expect(media.getByText('Verstanden: Fotos vom Abend')).toBeVisible()
    await expect(media.locator('[data-tile]')).toHaveCount(6)
    await expect(media.locator('[data-refine]')).toHaveCount(2)

    // follow-up carries the conversation id and renders people
    await ask(page, 'Wer war dabei')
    const people = page.locator('[data-result="people"]')
    await expect(people).toBeVisible()
    await expect(people.locator('a[href*="/people/"]')).toHaveCount(3)
    expect(conversationIds[0]).toBeUndefined()
    expect(conversationIds[1]).toMatch(/^[A-Za-z0-9_-]{22}$/)

    // stat with attachments
    await ask(page, 'Wie viele Fotos von mir')
    const stat = page.locator('[data-result="stat"]')
    await expect(stat.getByText('42')).toBeVisible()
    await expect(stat.getByText('in 2 Alben dieses Jahr')).toBeVisible()
    const attachments = stat.locator('[data-attachments]')
    await expect(attachments.locator('[data-attachment-image]')).toHaveCount(2)
    await expect(attachments.locator('[data-attachment-file]')).toHaveCount(1)
    await attachments.locator('[data-attachment-image]').first().click()
    const viewer = page.locator('[data-attachment-viewer]')
    await expect(viewer).toBeVisible()
    await expect(viewer.getByRole('link', { name: 'Speichern' })).toHaveAttribute(
      'download',
      'fotos-pro-monat.png',
    )
    await viewer.getByRole('button', { name: 'Schließen' }).click()
    await expect(viewer).toBeHidden()

    // album
    await ask(page, 'Mach ein Album daraus')
    const album = page.locator('[data-result="album"]')
    await expect(album.getByRole('link', { name: 'Album öffnen' })).toHaveAttribute(
      'href',
      /\/albums\//,
    )

    // clarify, answered with an option chip
    await ask(page, 'Welche Party war das')
    const clarify = page.locator('[data-result="clarify"]')
    await expect(clarify.getByText('Welches Album meinst du?')).toBeVisible()
    await expect(clarify.locator('[data-option]')).toHaveCount(2)
    await clarify.locator('[data-option]').first().click()
    await expect(page.locator('[data-result="media"]')).toHaveCount(2)

    // empty with suggestions
    await ask(page, 'nichts unicorn')
    const empty = page.locator('[data-result="empty"]')
    await expect(empty.locator('[data-empty="search"]')).toBeVisible()
    await expect(empty.locator('[data-refine]')).toHaveCount(2)
  })

  test('saves a chip, shows it in the gallery and runs it without the model', async ({ page }) => {
    await page.goto(`/e/${SLUG}/search`)
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await ask(page, 'Fotos vom Abend')
    await page.locator('[data-save-chip]').click()
    const label = page.locator('[data-chip-label]')
    await expect(label).toHaveValue('Verstanden: Fotos vom Abend')
    await label.fill('Abendfotos')
    await page.locator('[data-save-confirm]').click()
    await expect(page.getByRole('status').filter({ hasText: 'Chip gespeichert' })).toBeVisible()

    await page.goto(`/e/${SLUG}/photos`)
    const chip = page.locator('[data-command]', { hasText: 'Abendfotos' })
    await expect(chip).toBeVisible()
    await chip.click()
    await expect(page).toHaveURL(/\/search\?command=/)
    await expect(page.locator('[data-result="media"]')).toBeVisible()
    await expect(page.getByText('Abendfotos').first()).toBeVisible()
  })

  test('falls back to plain search when the assistant is not configured', async ({
    page,
    request,
  }) => {
    await setAgentConfigured(request, false)
    await page.goto(`/e/${SLUG}/search`)
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await ask(page, 'die Torte')
    await expect(
      page.getByText('Die Suche funktioniert, der Assistent ist noch nicht eingerichtet.'),
    ).toBeVisible()
    await expect(page.locator('[data-result="media"] [data-tile]')).toHaveCount(5)
    await expect(page.locator('[data-save-chip]')).toHaveCount(0)
  })

  test('the member search lists and manages saved chips with tool tags', async ({ page }) => {
    await page.goto('/search')
    await expect(page.locator('html[data-hydrated="true"]')).toBeAttached()
    await expect(page.getByText('Alle Alben')).toBeVisible()
    await page.getByRole('link', { name: 'Gespeicherte Chips' }).click()
    await expect(page).toHaveURL(/\/search\/saved$/)
    const rows = page.locator('[data-command]')
    await expect(rows).toHaveCount(2)
    const tool = rows.filter({ hasText: 'Mit wem am meisten' })
    await expect(tool.locator('[data-tag="tool"]')).toHaveText('Tool')
    await expect(tool.locator('[data-tag="agent"]')).toHaveText('vom Assistenten erstellt')
    await expect(rows.filter({ hasText: 'Gruppenfotos' }).locator('[data-tag]')).toHaveCount(0)
    await tool.locator('[data-delete-command]').click()
    await page.locator('dialog[open] [data-confirm]').click()
    await expect(rows).toHaveCount(1)
  })
})
