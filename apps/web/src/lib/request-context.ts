import { createIsomorphicFn } from '@tanstack/react-start'
import { getRequestHeader, getResponse } from '@tanstack/react-start/server'

type IncomingName = 'cookie' | 'accept-language'

/** Reads a header of the incoming request during SSR; undefined on the client or outside a request. */
export const incomingHeader = createIsomorphicFn()
  .server((name: IncomingName): string | undefined => {
    try {
      return getRequestHeader(name)
    } catch {
      return undefined
    }
  })
  .client((_name: IncomingName): string | undefined => undefined)

/** Appends a header to the SSR response (used to relay Set-Cookie from the API); no-op on the client. */
export const appendResponseHeader = createIsomorphicFn()
  .server((name: string, value: string): void => {
    try {
      getResponse().headers.append(name, value)
    } catch {
      // Outside a request context (build, tests).
    }
  })
  .client((_name: string, _value: string): void => {})
