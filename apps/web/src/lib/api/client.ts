import createClient, { type Middleware } from 'openapi-fetch'
import { appendResponseHeader, incomingHeader } from '~/lib/request-context'
import type { ErrorCode, ErrorResponse, paths } from './types'

export class ApiError extends Error {
  readonly status: number
  readonly code: ErrorCode | 'network' | 'unknown'
  readonly details?: Record<string, unknown>

  constructor(
    status: number,
    code: ApiError['code'],
    message: string,
    details?: Record<string, unknown>,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  static from(status: number, body: unknown, fallback = `Request failed with ${status}`): ApiError {
    const error = (body as Partial<ErrorResponse> | undefined)?.error
    if (error && typeof error.code === 'string') {
      return new ApiError(status, error.code, error.message ?? fallback, error.details)
    }
    return new ApiError(status, status === 0 ? 'network' : 'unknown', fallback)
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError
}

export function apiBaseUrl(): string {
  if (import.meta.env.SSR) {
    return process.env.API_INTERNAL_URL ?? 'http://localhost:8080/api/v1'
  }
  return '/api/v1'
}

/** During SSR forward the browser's cookies and language to the API and relay Set-Cookie back. */
const ssrForwarding: Middleware = {
  onRequest({ request }) {
    if (!import.meta.env.SSR) return
    const cookie = incomingHeader('cookie')
    if (cookie) request.headers.set('cookie', cookie)
    const language = incomingHeader('accept-language')
    if (language) request.headers.set('accept-language', language)
  },
  onResponse({ response }) {
    if (!import.meta.env.SSR) return
    for (const cookie of response.headers.getSetCookie()) appendResponseHeader('set-cookie', cookie)
  },
}

export const api = createClient<paths>({
  baseUrl: apiBaseUrl(),
  credentials: 'same-origin',
})
api.use(ssrForwarding)

type Result<T> = { data?: T; error?: unknown; response: Response }

/** Unwraps an openapi-fetch result, throwing a typed ApiError for `{error}` bodies. */
export function ok<T>(result: Result<T>): T {
  if (result.error !== undefined || !result.response.ok) {
    throw ApiError.from(result.response.status, result.error)
  }
  return result.data as T
}

/** Like `ok` for endpoints that return no body. */
export function okVoid(result: Result<unknown>): void {
  if (result.error !== undefined || !result.response.ok) {
    throw ApiError.from(result.response.status, result.error)
  }
}
