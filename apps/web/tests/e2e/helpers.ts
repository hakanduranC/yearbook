import type { APIRequestContext, BrowserContext } from '@playwright/test'

export const MOCK = 'http://localhost:8089'
export const SLUG = 'demo-party-abc123'
export const SLUG2 = 'sommerfest-xyz789'
/** Ids the mock derives from short names, padded to 22 characters. */
export const mockId = (name: string) => name.padEnd(22, '0').slice(0, 22)

export async function resetMock(request: APIRequestContext) {
  await request.post(`${MOCK}/__mock/reset`)
}

export async function setAgentConfigured(request: APIRequestContext, on: boolean) {
  await request.post(`${MOCK}/__mock/agent?configured=${on ? 1 : 0}`)
}

/** The mock signs any yb_session cookie in as the seeded member. */
export async function signIn(context: BrowserContext) {
  await context.addCookies([{ name: 'yb_session', value: 'mock', domain: 'localhost', path: '/' }])
}

/** Claims a person for the seeded member straight on the mock, bypassing the UI. */
export async function claimOnMock(request: APIRequestContext, personKey: string) {
  await request.post(`${MOCK}/api/v1/people/${mockId(personKey)}/claim`, {
    headers: { cookie: 'yb_session=mock' },
  })
}
